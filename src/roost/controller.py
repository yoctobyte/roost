from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib  # noqa: E402

from roost import state as state_mod
from roost import tmux_adapter
from roost.config import POLL_INTERVAL_MS, PREVIEW_LINES, SESSION_NAME
from roost.models import AppState, WindowInfo
from roost.tmux_adapter import TmuxError

StateListener = Callable[[AppState], None]
ErrorListener = Callable[[str], None]


class Controller:
    def __init__(self) -> None:
        self._session = SESSION_NAME
        self._state = AppState()
        self._state_listeners: list[StateListener] = []
        self._error_listeners: list[ErrorListener] = []
        self._poll_source: int | None = None
        self._was_fresh = False
        self._snapshot_key: tuple = ()
        # Whether to persist session snapshots. Main window flips this
        # from Settings after construction.
        self.remember_tabs = True

    @property
    def session(self) -> str:
        return self._session

    @property
    def state(self) -> AppState:
        return self._state

    def on_state_changed(self, listener: StateListener) -> None:
        self._state_listeners.append(listener)

    def on_error(self, listener: ErrorListener) -> None:
        self._error_listeners.append(listener)

    def start(self) -> None:
        self._was_fresh = tmux_adapter.ensure_session(self._session)
        self.sync_now()
        if self._poll_source is None:
            self._poll_source = GLib.timeout_add(POLL_INTERVAL_MS, self._tick)

    @property
    def was_fresh_start(self) -> bool:
        return self._was_fresh

    def stop(self) -> None:
        if self._poll_source is not None:
            GLib.source_remove(self._poll_source)
            self._poll_source = None

    def sync_now(self) -> None:
        try:
            windows = tmux_adapter.list_windows_with_previews(
                self._session, PREVIEW_LINES
            )
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        selected = self._state.selected_id
        if selected is not None and not any(w.id == selected for w in windows):
            selected = None
        self._set_state(AppState(windows=tuple(windows), selected_id=selected))

    def new_console(self, name: str | None = None) -> None:
        try:
            wid = tmux_adapter.new_window(self._session, name=name)
            tmux_adapter.select_window(wid)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        self._state = AppState(
            windows=self._state.windows, selected_id=wid
        )
        self.sync_now()

    def rename_console(self, window_id: str, new_name: str) -> None:
        try:
            tmux_adapter.rename_window(window_id, new_name)
        except TmuxError as exc:
            self._emit_error(str(exc))
        self.sync_now()

    def move_console(self, window_id: str, direction: int) -> None:
        ordered = sorted(self._state.windows, key=lambda w: w.index)
        idx = next(
            (i for i, w in enumerate(ordered) if w.id == window_id), -1
        )
        if idx < 0:
            return
        target = idx + direction
        if target < 0 or target >= len(ordered):
            return
        try:
            tmux_adapter.swap_windows(window_id, ordered[target].id)
        except TmuxError as exc:
            self._emit_error(str(exc))
        self.sync_now()

    def close_console(self, window_id: str) -> None:
        try:
            tmux_adapter.kill_window(window_id)
        except TmuxError as exc:
            self._emit_error(str(exc))
        if self._state.selected_id == window_id:
            self._state = AppState(
                windows=self._state.windows, selected_id=None
            )
        self.sync_now()

    def select(self, window_id: str) -> None:
        try:
            tmux_adapter.select_window(window_id)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        self._set_state(
            AppState(windows=self._state.windows, selected_id=window_id)
        )

    def clear_selection(self) -> None:
        self._set_state(
            AppState(windows=self._state.windows, selected_id=None)
        )

    def selected_window(self) -> WindowInfo | None:
        if self._state.selected_id is None:
            return None
        return self._state.by_id(self._state.selected_id)

    def _tick(self) -> bool:
        self.sync_now()
        return True

    def restore_windows(self, entries) -> None:
        for w in entries:
            try:
                wid = tmux_adapter.new_window(
                    self._session,
                    name=w.name or None,
                    cwd=w.cwd or None,
                )
            except TmuxError as exc:
                self._emit_error(str(exc))
                continue
            if w.last_command:
                try:
                    tmux_adapter.send_text(wid, w.last_command)
                except TmuxError:
                    pass
        self.sync_now()

    def _set_state(self, state: AppState) -> None:
        self._state = state
        for listener in list(self._state_listeners):
            listener(state)
        self._maybe_save_snapshot(state)

    def _maybe_save_snapshot(self, state: AppState) -> None:
        if not self.remember_tabs:
            return
        snap = state_mod.build_snapshot(self._session, state.windows)
        key = state_mod.change_key(snap.windows)
        if key == self._snapshot_key:
            return
        self._snapshot_key = key
        try:
            state_mod.save(snap)
        except OSError:
            pass

    def _emit_error(self, message: str) -> None:
        for listener in list(self._error_listeners):
            listener(message)
