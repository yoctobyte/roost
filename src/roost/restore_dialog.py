import time

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from roost.state import SavedWindow, Snapshot


class RestoreDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, snap: Snapshot) -> None:
        super().__init__(
            title="Restore previous session",
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(560, 420)
        self.add_button("Skip", Gtk.ResponseType.CANCEL)
        self.add_button("Restore selected", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        age = _format_age(max(0.0, time.time() - snap.saved_at))
        header = Gtk.Label(xalign=0.0)
        header.set_markup(
            f"<b>roost has a saved session from {GLib.markup_escape_text(age)}.</b>"
        )
        box.add(header)

        info = Gtk.Label(
            label=(
                "Pick the tabs you want to recreate. Each tab opens in "
                "the directory its last command was run from. That "
                "command is placed on the shell prompt — not executed — "
                "so you can press Enter to re-run or edit it first."
            ),
            xalign=0.0,
        )
        info.set_line_wrap(True)
        box.add(info)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        self._rows: list[tuple[Gtk.CheckButton, SavedWindow]] = []
        for w in snap.windows:
            row = Gtk.ListBoxRow()
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hb.set_margin_top(6)
            hb.set_margin_bottom(6)
            hb.set_margin_start(8)
            hb.set_margin_end(8)

            check = Gtk.CheckButton()
            check.set_active(True)
            check.set_can_focus(True)
            hb.pack_start(check, False, False, 0)

            text = Gtk.Label(xalign=0.0)
            text.set_line_wrap(True)
            text.set_selectable(True)
            markup_parts = [
                f"<b>{GLib.markup_escape_text(w.name or '(unnamed)')}</b>"
            ]
            restore_cwd = w.restore_cwd()
            if restore_cwd:
                markup_parts.append(
                    f"<small>{GLib.markup_escape_text(restore_cwd)}</small>"
                )
            if w.last_command:
                markup_parts.append(
                    f"<tt>{GLib.markup_escape_text(w.last_command)}</tt>"
                )
                # The shell may have moved on after the command finished;
                # say so, since we reopen where the command was launched.
                if w.cwd and w.cwd != restore_cwd:
                    markup_parts.append(
                        f"<small><i>tab had since moved to "
                        f"{GLib.markup_escape_text(w.cwd)}</i></small>"
                    )
            else:
                markup_parts.append(
                    "<small><i>no command recorded — opens a shell</i></small>"
                )
            text.set_markup("\n".join(markup_parts))
            hb.pack_start(text, True, True, 0)

            row.add(hb)
            list_box.add(row)
            self._rows.append((check, w))

        scrolled.add(list_box)
        box.add(scrolled)

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        select_all = Gtk.Button(label="Select all")
        select_all.connect("clicked", lambda *_: self._set_all(True))
        btn_bar.pack_start(select_all, False, False, 0)
        select_none = Gtk.Button(label="Select none")
        select_none.connect("clicked", lambda *_: self._set_all(False))
        btn_bar.pack_start(select_none, False, False, 0)
        box.add(btn_bar)

        self.show_all()

    def _set_all(self, value: bool) -> None:
        for check, _ in self._rows:
            check.set_active(value)

    def get_selected(self) -> list[SavedWindow]:
        return [w for check, w in self._rows if check.get_active()]


def _format_age(secs: float) -> str:
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"
