"""Status tab: which boxes answer, and every Claude session roost remembers.

Boxes that are switched off used to announce themselves with a modal
error dialog; here they are just a line. The Claude list is the restore
point after a reboot or crash: an ended session comes back, resumed, in
a new tab with one click.
"""

import time
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from roost.claude_sessions import LiveSession, SessionRecord
from roost.settings import Settings, host_marker

_STATUS_LABELS = {"busy": "working", "idle": "idle"}


class StatusPage(Gtk.ScrolledWindow):
    def __init__(
        self,
        settings: Settings,
        on_restore: Callable[[SessionRecord], None],
        on_forget: Callable[[str], None],
        on_show: Callable[[str, str], None],
    ) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._settings = settings
        self._on_restore = on_restore
        self._on_forget = on_forget
        self._on_show = on_show
        self._key: tuple = ()

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(self._box, f"set_margin_{side}")(16)
        self.add(self._box)
        self._apply_bg()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._apply_bg()
        self._key = ()

    def _apply_bg(self) -> None:
        theme = self._settings.theme_obj()
        bg = Gdk.RGBA()
        bg.parse(theme.bg)
        self._box.override_background_color(Gtk.StateFlags.NORMAL, bg)
        self.override_background_color(Gtk.StateFlags.NORMAL, bg)
        viewport = self._box.get_parent()
        if isinstance(viewport, Gtk.Viewport):
            viewport.override_background_color(Gtk.StateFlags.NORMAL, bg)

    def refresh(
        self,
        boxes: list[tuple[str | None, bool | None, str, float]],
        records: list[SessionRecord],
        live: dict[str, LiveSession],
        shown_windows: set[tuple[str, str]],
    ) -> None:
        """Rebuild, but only when something visible actually changed."""
        key = (
            tuple(boxes),
            tuple(
                (
                    r.session_id, r.name, r.cwd, r.ended, r.last_seen, r.tmux,
                    live[r.session_id].status if r.session_id in live else "",
                )
                for r in records
            ),
            tuple(sorted(shown_windows)),
        )
        if key == self._key:
            return
        self._key = key
        for child in self._box.get_children():
            self._box.remove(child)

        self._heading("Boxes")
        grid = self._grid()
        for row, (dest, ok, err, since) in enumerate(boxes):
            name = f"{host_marker(dest)}  {dest or 'this machine'}"
            if ok is None:
                state, detail = "…", "not polled yet"
            elif ok:
                state, detail = "● online", f"since {_when(since)}"
            else:
                state, detail = "○ offline", f"since {_when(since)} — {err}"
            grid.attach(self._label(name), 0, row, 1, 1)
            grid.attach(self._label(state, bold=bool(ok)), 1, row, 1, 1)
            grid.attach(self._label(detail, dim=True, wrap=True), 2, row, 1, 1)
        self._box.pack_start(grid, False, False, 0)

        live_n = sum(1 for r in records if not r.ended)
        self._heading(
            f"Claude sessions on this machine — {live_n} running, "
            f"{len(records) - live_n} ended"
        )
        if not records:
            self._box.pack_start(
                self._label("None seen yet.", dim=True), False, False, 0
            )
        grid = self._grid()
        for row, rec in enumerate(records):
            title = rec.name or rec.session_id[:8]
            grid.attach(self._label(title, bold=not rec.ended), 0, row, 1, 1)
            if rec.ended:
                state = f"ended · last seen {_when(rec.last_seen)}"
            else:
                s = live[rec.session_id].status if rec.session_id in live else ""
                where = "tmux " + rec.tmux.split(".")[0] if rec.tmux else "outside tmux"
                state = f"{_STATUS_LABELS.get(s, s or 'running')} · {where}"
            grid.attach(self._label(state, dim=rec.ended), 1, row, 1, 1)
            path = self._label(rec.cwd, dim=True, wrap=True)
            path.set_tooltip_text(f"{rec.command}\nsession {rec.session_id}")
            grid.attach(path, 2, row, 1, 1)
            grid.attach(self._actions(rec, shown_windows), 3, row, 1, 1)
        self._box.pack_start(grid, False, False, 0)
        self._box.show_all()

    def _actions(
        self, rec: SessionRecord, shown_windows: set[tuple[str, str]]
    ) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        if rec.ended:
            restore = Gtk.Button(label="Restore")
            restore.set_tooltip_text(
                f"New tab in {rec.cwd or '~'}, running:\n{rec.command}"
            )
            restore.connect("clicked", lambda *_: self._on_restore(rec))
            box.pack_start(restore, False, False, 0)
            forget = Gtk.Button(label="Forget")
            forget.set_tooltip_text("Drop it from this list")
            forget.connect("clicked", lambda *_: self._on_forget(rec.session_id))
            box.pack_start(forget, False, False, 0)
        else:
            where = _tmux_window(rec.tmux)
            if where is not None and where in shown_windows:
                show = Gtk.Button(label="Show")
                show.connect("clicked", lambda *_: self._on_show(*where))
                box.pack_start(show, False, False, 0)
        return box

    # -- widgets ------------------------------------------------------------

    def _fg(self) -> Gdk.RGBA:
        fg = Gdk.RGBA()
        fg.parse(self._settings.theme_obj().fg)
        return fg

    def _heading(self, text: str) -> None:
        label = Gtk.Label(xalign=0.0)
        label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        label.set_margin_top(10)
        label.override_color(Gtk.StateFlags.NORMAL, self._fg())
        self._box.pack_start(label, False, False, 0)

    def _grid(self) -> Gtk.Grid:
        grid = Gtk.Grid()
        grid.set_column_spacing(18)
        grid.set_row_spacing(4)
        return grid

    def _label(
        self, text: str, bold: bool = False, dim: bool = False, wrap: bool = False
    ) -> Gtk.Label:
        label = Gtk.Label(xalign=0.0)
        markup = GLib.markup_escape_text(text)
        if bold:
            markup = f"<b>{markup}</b>"
        label.set_markup(markup)
        if wrap:
            label.set_hexpand(True)
            label.set_line_wrap(True)
            label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        fg = self._fg()
        if dim:
            fg.alpha = 0.65
        label.override_color(Gtk.StateFlags.NORMAL, fg)
        return label


def _tmux_window(target: str) -> tuple[str, str] | None:
    if ":" not in target:
        return None
    session, _, rest = target.partition(":")
    return session, rest.split(".", 1)[0]


def _when(ts: float) -> str:
    if not ts:
        return "?"
    t = time.localtime(ts)
    if time.strftime("%Y-%m-%d", t) == time.strftime("%Y-%m-%d"):
        return time.strftime("%H:%M", t)
    return time.strftime("%a %d %b %H:%M", t)
