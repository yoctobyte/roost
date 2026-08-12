import threading
import time
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib  # noqa: E402

from roost import state as state_mod
from roost import tmux_adapter
from roost.config import POLL_INTERVAL_MS, PREVIEW_LINES, SESSION_NAME
from roost.models import AppState, WindowInfo
from roost.tmux_adapter import TmuxError

# Sentinel: sync every box, as opposed to one named destination.
_ALL_BOXES = object()

# How long an unreachable box is left alone before being retried.
OFFLINE_RETRY_SECONDS = 30.0

StateListener = Callable[[AppState], None]
ErrorListener = Callable[[str], None]


class Controller:
    def __init__(self, dest: str | None = None) -> None:
        self._session = SESSION_NAME
        # ssh destination of the box this controller talks to, or None
        # for this machine. Still always None until the GUI can add a
        # box; the plumbing below is already destination-agnostic.
        self._dest = dest
        # Boxes to poll. None is this machine, which is always watched.
        self._boxes: list[str | None] = [None]
        # Destinations that failed their last poll, so the error is
        # reported once rather than every 1.5 seconds.
        self._reported_offline: set[str | None] = set()
        # A box that failed is not retried until this time. Without it a
        # single unreachable machine burns the whole connect timeout on
        # every poll, forever.
        self._retry_after: dict[str | None, float] = {}
        self._state = AppState()
        self._state_listeners: list[StateListener] = []
        self._error_listeners: list[ErrorListener] = []
        self._poll_source: int | None = None
        self._was_fresh = False
        self._snapshot_key: tuple = ()
        # Whether to persist session snapshots. Main window flips this
        # from Settings after construction.
        self.remember_tabs = True
        # The snapshot as it was on disk before we touched anything.
        # Read here, at construction, because start() creates the tmux
        # session and syncs -- which would otherwise overwrite the file
        # with the fresh empty session before anyone offered to restore
        # from it.
        self.previous_snapshot = state_mod.load()
        # Saving stays off until the restore offer has been resolved, so
        # a crash snapshot survives long enough to be acted on.
        self._snapshots_armed = False
        # window id -> (command, cwd it was launched from). Carried
        # across polls so a window sitting idle at a prompt still knows
        # what it last ran.
        self._command_memory: dict[str, tuple[str, str]] = {}
        # Polling runs on a worker thread. Locally a poll costs about a
        # millisecond, but once a host is reached over ssh it is tens of
        # milliseconds at best and seconds when the box is unreachable --
        # which would freeze the GUI if it ran on the main loop.
        self._poll_thread: threading.Thread | None = None
        self._stopped = False
        # Called with (dest, session) right after roost creates a
        # session, so the window can stamp its tmux options (status bar,
        # mouse mode) onto it. A session that appears any other way is
        # somebody else's and is left exactly as it is.
        self.on_session_created: Callable[[str | None, str], None] | None = None

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

    def set_boxes(self, boxes) -> None:
        """Destinations to watch besides this machine."""
        self._boxes = [None] + [b for b in boxes if b]

    def start(self) -> None:
        # Connecting must never change a box: roost lists what is
        # already there, whoever started it, and a session is created
        # only when the user asks for one. "Fresh" therefore means this
        # machine reported no sessions at all -- not that we made one.
        self._was_fresh = not tmux_adapter.has_sessions(None)
        self.sync_now()
        if self._poll_source is None:
            self._poll_source = GLib.timeout_add(POLL_INTERVAL_MS, self._tick)

    @property
    def was_fresh_start(self) -> bool:
        return self._was_fresh

    def arm_snapshots(self) -> None:
        """Allow snapshots to be written from now on.

        Called once the restore offer has been resolved -- until then a
        write would destroy the very state the offer is made from.
        """
        if self._snapshots_armed:
            return
        self._snapshots_armed = True
        self._maybe_save_snapshot(self._state)

    def stop(self) -> None:
        self._stopped = True
        if self._poll_source is not None:
            GLib.source_remove(self._poll_source)
            self._poll_source = None

    def sync_now(self, only_dest: object = _ALL_BOXES) -> None:
        """Refresh synchronously.

        Used after a user-initiated mutation, where the caller wants the
        result reflected immediately. This runs on the main thread, so
        it must not touch a box it does not have to: polling every box
        here would make each rename or tab close wait out the connect
        timeout of any machine that happens to be down. Mutations pass
        the destination they changed, and every other box keeps the
        windows it already had.
        """
        if only_dest is _ALL_BOXES:
            windows, errors = self._fetch_all()
        else:
            windows, errors = self._fetch_one(only_dest)  # type: ignore[arg-type]
        self._apply_windows(windows)
        for message in errors:
            self._emit_error(message)

    def _fetch_one(self, dest: str | None):
        """Re-poll a single box, keeping what the others last reported."""
        kept = [w for w in self._state.windows if w.dest != dest]
        try:
            fresh = tmux_adapter.fetch_box(dest, PREVIEW_LINES)
        except TmuxError as exc:
            return kept, [f"{dest or 'this machine'}: {exc}"]
        return kept + fresh, []

    def _apply_windows(self, windows) -> None:
        selected = self._state.selected_id
        if selected is not None and not any(w.key == selected for w in windows):
            selected = None
        self._remember_commands(windows)
        self._set_state(AppState(windows=tuple(windows), selected_id=selected))

    def _remember_commands(self, windows) -> None:
        live = set()
        for w in windows:
            live.add(w.key)
            if w.last_command:
                self._command_memory[w.key] = (w.last_command, w.current_path)
        for stale in [k for k in self._command_memory if k not in live]:
            del self._command_memory[stale]

    def new_console(
        self,
        name: str | None = None,
        dest: str | None = None,
        session: str | None = None,
    ) -> None:
        """Open a window, on the given box and session.

        With nothing specified it follows the current selection, so a
        new tab lands beside the one being worked in rather than
        somewhere else entirely. If that box has no session at all yet,
        one is created -- the only moment roost ever creates a session,
        and only because the user asked for a window.
        """
        if dest is None and session is None:
            current = self.selected_window()
            if current is not None:
                dest, session = current.dest, current.session
        if session is None:
            existing = [
                w.session for w in self._state.windows if w.dest == dest
            ]
            session = existing[0] if existing else None
        try:
            if session is None:
                tmux_adapter.create_session(self._session, dest)
                session = self._session
                wid = tmux_adapter.new_window(session, name=name, dest=dest) if name else None
                if wid is None:
                    self.sync_now(dest)
                    return
            else:
                wid = tmux_adapter.new_window(session, name=name, dest=dest)
            tmux_adapter.select_window(wid, dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        self.sync_now(dest)
        for w in self._state.windows:
            if w.dest == dest and w.session == session and w.id == wid:
                self._set_state(
                    AppState(windows=self._state.windows, selected_id=w.key)
                )
                break

    @property
    def boxes(self) -> list[str | None]:
        return list(self._boxes)

    def is_offline(self, dest: str | None) -> bool:
        return dest in self._reported_offline

    def new_session(self, dest: str | None = None, name: str | None = None) -> None:
        """Start a session on a box, and select it.

        The name is nudged until it is free rather than reused, because
        tmux would otherwise refuse -- and a box may already hold a
        session called "roost" that the user started themselves.
        """
        taken = {w.session for w in self._state.windows if w.dest == dest}
        base = name or self._session
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        try:
            tmux_adapter.create_session(candidate, dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        self._session_created(dest, candidate)
        self.sync_now(dest)
        for w in self._state.windows:
            if w.dest == dest and w.session == candidate:
                self._set_state(
                    AppState(windows=self._state.windows, selected_id=w.key)
                )
                break

    def _resolve(self, key: str) -> WindowInfo | None:
        return self._state.by_key(key)

    def rename_console(self, key: str, new_name: str) -> None:
        win = self._resolve(key)
        if win is None:
            return
        try:
            tmux_adapter.rename_window(win.id, new_name, win.dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
        self.sync_now(win.dest)

    def _siblings(self, win: WindowInfo) -> list[WindowInfo]:
        """Windows sharing this one's box and session, in tmux order.

        Swapping is a within-session operation: tmux cannot exchange a
        window with one on another server, and reordering across two
        boxes has no meaning.
        """
        return sorted(
            (
                w
                for w in self._state.windows
                if w.dest == win.dest and w.session == win.session
            ),
            key=lambda w: w.index,
        )

    def move_console(self, key: str, direction: int) -> None:
        win = self._resolve(key)
        if win is None:
            return
        ordered = self._siblings(win)
        idx = next((i for i, w in enumerate(ordered) if w.key == key), -1)
        if idx < 0:
            return
        target = idx + direction
        if target < 0 or target >= len(ordered):
            return
        try:
            tmux_adapter.swap_windows(win.id, ordered[target].id, win.dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
        self.sync_now(win.dest)

    def move_to(self, key: str, target_key: str) -> None:
        """Move `key` to the current position of `target_key`,
        shifting intermediate windows via adjacent swaps."""
        if key == target_key:
            return
        win = self._resolve(key)
        target = self._resolve(target_key)
        if win is None or target is None:
            return
        if (win.dest, win.session) != (target.dest, target.session):
            return  # cannot reorder across sessions or boxes
        ordered: list[WindowInfo] = self._siblings(win)
        src = next((i for i, w in enumerate(ordered) if w.key == key), -1)
        dst = next((i for i, w in enumerate(ordered) if w.key == target_key), -1)
        if src < 0 or dst < 0:
            return
        try:
            while src != dst:
                step = 1 if dst > src else -1
                neighbor = ordered[src + step]
                tmux_adapter.swap_windows(
                    ordered[src].id, neighbor.id, win.dest
                )
                ordered[src], ordered[src + step] = (
                    ordered[src + step],
                    ordered[src],
                )
                src += step
        except TmuxError as exc:
            self._emit_error(str(exc))
        self.sync_now(win.dest)

    def reorder_to(self, desired_keys: list[str]) -> None:
        """Reorder to match `desired_keys`, one session at a time.

        Keys missing from the current state are skipped, and current
        windows not in `desired_keys` keep their relative tail position.
        Each (box, session) is reordered independently, since tmux can
        only swap windows living on the same server.
        """
        by_source: dict[tuple, list[str]] = {}
        for key in desired_keys:
            win = self._resolve(key)
            if win is not None:
                by_source.setdefault((win.dest, win.session), []).append(key)

        changed = False
        for (dest, session), wanted in by_source.items():
            ordered = [
                w
                for w in sorted(self._state.windows, key=lambda w: w.index)
                if w.dest == dest and w.session == session
            ]
            current = [w.key for w in ordered]
            desired = [k for k in wanted if k in current]
            for key in current:
                if key not in desired:
                    desired.append(key)
            if desired == current:
                continue
            ids = {w.key: w.id for w in ordered}
            work = list(current)
            try:
                for pos, target in enumerate(desired):
                    if work[pos] == target:
                        continue
                    j = work.index(target)
                    tmux_adapter.swap_windows(ids[work[pos]], ids[work[j]], dest)
                    work[pos], work[j] = work[j], work[pos]
                changed = True
            except TmuxError as exc:
                self._emit_error(str(exc))
        if changed:
            self.sync_now(dest)

    def close_console(self, key: str) -> None:
        win = self._resolve(key)
        if win is None:
            return
        try:
            tmux_adapter.kill_window(win.id, win.dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
        if self._state.selected_id == key:
            self._state = AppState(
                windows=self._state.windows, selected_id=None
            )
        self.sync_now(win.dest)

    def select(self, key: str) -> None:
        win = self._resolve(key)
        if win is None:
            return
        try:
            tmux_adapter.select_window(win.id, win.dest)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        self._set_state(
            AppState(windows=self._state.windows, selected_id=key)
        )

    def clear_selection(self) -> None:
        self._set_state(
            AppState(windows=self._state.windows, selected_id=None)
        )

    def selected_window(self) -> WindowInfo | None:
        if self._state.selected_id is None:
            return None
        return self._state.by_key(self._state.selected_id)

    def _tick(self) -> bool:
        """Kick off a background poll, unless one is still running.

        Skipping while a fetch is in flight means a slow or unreachable
        host throttles itself instead of queueing up threads.
        """
        if self._stopped:
            return False
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return True
        self._poll_thread = threading.Thread(target=self._poll_worker, daemon=True)
        self._poll_thread.start()
        return True

    def _fetch_all(self) -> tuple[list, list[str]]:
        """Poll every box. A box that fails is skipped, not fatal.

        One unreachable machine must not blank out the tabs belonging to
        the others, so each box is fetched independently and its failure
        only costs its own windows.
        """
        windows: list = []
        errors: list[str] = []
        now = time.monotonic()
        for dest in list(self._boxes):
            if now < self._retry_after.get(dest, 0.0):
                # Still cooling off; keep whatever it last reported so
                # its tabs do not flicker away while it is down.
                windows.extend(
                    w for w in self._state.windows if w.dest == dest
                )
                continue
            try:
                windows.extend(tmux_adapter.fetch_box(dest, PREVIEW_LINES))
            except TmuxError as exc:
                self._retry_after[dest] = now + OFFLINE_RETRY_SECONDS
                if dest not in self._reported_offline:
                    self._reported_offline.add(dest)
                    errors.append(f"{dest or 'this machine'}: {exc}")
                continue
            self._retry_after.pop(dest, None)
            self._reported_offline.discard(dest)
        return windows, errors

    def _poll_worker(self) -> None:
        windows, errors = self._fetch_all()
        GLib.idle_add(self._deliver_windows, windows, errors)

    def _deliver_windows(self, windows, errors=()) -> bool:
        # Back on the main thread: safe to touch state and widgets.
        if self._stopped:
            return False
        self._apply_windows(windows)
        for message in errors:
            self._emit_error(message)
        return False

    def _deliver_error(self, message: str) -> bool:
        if self._stopped:
            return False
        self._emit_error(message)
        return False

    def restore_windows(self, entries) -> None:
        """Recreate the given windows on this machine.

        start() no longer creates a session, so restoring has to make
        one -- this is a user asking for it, which is the only reason
        roost ever creates a session.
        """
        if not entries:
            return
        try:
            if not tmux_adapter.session_exists(self._session):
                tmux_adapter.create_session(self._session)
                self._session_created(None, self._session)
        except TmuxError as exc:
            self._emit_error(str(exc))
            return
        for w in entries:
            try:
                wid = tmux_adapter.new_window(
                    self._session,
                    name=w.name or None,
                    cwd=w.restore_cwd() or None,
                )
            except TmuxError as exc:
                self._emit_error(str(exc))
                continue
            if w.last_command:
                try:
                    tmux_adapter.send_text(wid, w.last_command)
                except TmuxError:
                    pass
        self.sync_now(None)

    def _session_created(self, dest: str | None, session: str) -> None:
        if self.on_session_created is not None:
            self.on_session_created(dest, session)

    def _set_state(self, state: AppState) -> None:
        self._state = state
        for listener in list(self._state_listeners):
            listener(state)
        self._maybe_save_snapshot(state)

    def _maybe_save_snapshot(self, state: AppState) -> None:
        if not self.remember_tabs or not self._snapshots_armed:
            return
        snap = state_mod.build_snapshot(
            self._session, state.windows, self._command_memory
        )
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
