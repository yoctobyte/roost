import shutil
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import Gdk, GLib, Gtk, Vte  # noqa: E402


class TerminalPage(Gtk.Box):
    def __init__(
        self,
        session: str,
        on_child_exited: Callable[[int], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_child_exited = on_child_exited

        self._vte = Vte.Terminal()
        self._vte.set_scrollback_lines(10000)
        self._vte.set_mouse_autohide(True)

        self.pack_start(self._vte, True, True, 0)

        tmux_bin = shutil.which("tmux") or "/usr/bin/tmux"
        self._vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,  # working dir
            [tmux_bin, "attach", "-t", f"={session}"],
            None,  # envv (inherit)
            GLib.SpawnFlags.DEFAULT,
            None,  # child setup
            None,  # child setup data
            -1,    # timeout
            None,  # cancellable
            self._on_spawn_ready,
            None,  # user data
        )

        self._vte.connect("child-exited", self._handle_child_exited)
        self._vte.connect("key-press-event", self._on_key_press)
        self._vte.connect("button-press-event", self._on_button_press)

    def grab_focus(self) -> None:  # type: ignore[override]
        # Defer to the idle loop so grab happens after any in-flight
        # focus-stealing from button clicks / page switches.
        GLib.idle_add(self._grab_focus_idle)

    def _grab_focus_idle(self) -> bool:
        self._vte.grab_focus()
        return False

    def apply_theme(self, fg_hex: str, bg_hex: str) -> None:
        fg = Gdk.RGBA()
        fg.parse(fg_hex)
        bg = Gdk.RGBA()
        bg.parse(bg_hex)
        self._vte.set_colors(fg, bg, None)

    def _on_key_press(self, _widget, event) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and shift:
            if event.keyval in (Gdk.KEY_C, Gdk.KEY_c):
                self._do_copy()
                return True
            if event.keyval in (Gdk.KEY_V, Gdk.KEY_v):
                self._do_paste()
                return True
        # Classic X shortcuts as a fallback: Ctrl+Insert copies,
        # Shift+Insert pastes.
        if ctrl and event.keyval == Gdk.KEY_Insert:
            self._do_copy()
            return True
        if shift and event.keyval == Gdk.KEY_Insert:
            self._do_paste()
            return True
        return False

    def _on_button_press(self, _widget, event) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button != Gdk.BUTTON_SECONDARY:
            return False
        self._show_context_menu(event)
        return True

    def _show_context_menu(self, event) -> None:
        menu = Gtk.Menu()

        copy_item = Gtk.MenuItem(label="Copy")
        copy_item.set_sensitive(self._vte.get_has_selection())
        copy_item.connect("activate", lambda *_: self._do_copy())
        menu.append(copy_item)

        paste_item = Gtk.MenuItem(label="Paste")
        paste_item.connect("activate", lambda *_: self._do_paste())
        menu.append(paste_item)

        menu.append(Gtk.SeparatorMenuItem())

        select_all = Gtk.MenuItem(label="Select All")
        select_all.connect("activate", lambda *_: self._vte.select_all())
        menu.append(select_all)

        menu.show_all()
        menu.attach_to_widget(self._vte, None)
        menu.popup_at_pointer(event)

    def _do_copy(self) -> None:
        if not self._vte.get_has_selection():
            return
        self._vte.copy_clipboard_format(Vte.Format.TEXT)
        # Mirror to PRIMARY so middle-click paste also works with the
        # most recent selection (VTE already updates PRIMARY on select,
        # this is belt-and-suspenders).
        text = _read_clipboard_text(Gdk.SELECTION_CLIPBOARD)
        if text is not None:
            _write_clipboard_text(Gdk.SELECTION_PRIMARY, text)

    def _do_paste(self) -> None:
        self._vte.paste_clipboard()

    def _on_spawn_ready(self, _terminal, _pid, error, _user_data) -> None:
        if error is not None:
            self._on_child_exited(-1)

    def _handle_child_exited(self, _terminal, status: int) -> None:
        self._on_child_exited(status)


def _read_clipboard_text(selection) -> str | None:
    clip = Gtk.Clipboard.get(selection)
    return clip.wait_for_text()


def _write_clipboard_text(selection, text: str) -> None:
    clip = Gtk.Clipboard.get(selection)
    clip.set_text(text, -1)
