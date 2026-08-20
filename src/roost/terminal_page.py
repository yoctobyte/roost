import shlex
import shutil
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import Gdk, GLib, Gtk, Vte  # noqa: E402

from roost import links, ssh, tmux_adapter  # noqa: E402


class TerminalPage(Gtk.Box):
    def __init__(
        self,
        session: str,
        on_child_exited: Callable[[int], None],
        dest: str | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_child_exited = on_child_exited
        self._session = session
        self._dest = dest
        self._intercept_scroll = True
        self._smooth_accum = 0.0

        self._vte = Vte.Terminal()
        self._vte.set_scrollback_lines(10000)
        self._vte.set_mouse_autohide(True)
        # OSC 8 links, for the programs that bother to emit them.
        try:
            self._vte.set_allow_hyperlink(True)
        except (AttributeError, TypeError):
            pass
        self._add_link_matcher()

        self.pack_start(self._vte, True, True, 0)

        tmux_bin = shutil.which("tmux") or "/usr/bin/tmux"
        if dest is None:
            argv = [tmux_bin, "attach", "-t", f"={session}"]
        else:
            # -t forces a pty on the far side, which tmux needs; the
            # attach itself is an ordinary tmux client over the same
            # multiplexed connection the polls use.
            argv = (
                ssh.ssh_args(dest)[:-1]
                + ["-t", dest, f"tmux attach -t {shlex.quote('=' + session)}"]
            )
        self._vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,  # working dir
            argv,
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
        self._vte.connect("scroll-event", self._on_scroll)

    def grab_focus(self) -> None:  # type: ignore[override]
        # Defer to the idle loop so grab happens after any in-flight
        # focus-stealing from button clicks / page switches.
        GLib.idle_add(self._grab_focus_idle)

    def _grab_focus_idle(self) -> bool:
        self._vte.grab_focus()
        return False

    def apply_theme(
        self,
        fg_hex: str,
        bg_hex: str,
        palette_hex: tuple[str, ...] | None = None,
    ) -> None:
        fg = Gdk.RGBA()
        fg.parse(fg_hex)
        bg = Gdk.RGBA()
        bg.parse(bg_hex)
        palette = None
        if palette_hex:
            palette = []
            for hex_color in palette_hex:
                rgba = Gdk.RGBA()
                rgba.parse(hex_color)
                palette.append(rgba)
        self._vte.set_colors(fg, bg, palette)

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
        # Bare PageUp drops the active pane into tmux copy-mode and
        # scrolls one page back. Successive presses keep scrolling.
        # PageDown is left alone — when in copy-mode tmux handles it
        # natively; outside copy-mode the application receives it.
        if event.keyval == Gdk.KEY_Page_Up and not (ctrl or shift):
            try:
                handled = tmux_adapter.enter_copy_mode_up(self._session)
            except tmux_adapter.TmuxError:
                return False
            return handled
        return False

    def set_intercept_scroll(self, intercept: bool) -> None:
        self._intercept_scroll = intercept
        self._smooth_accum = 0.0

    def _on_scroll(self, _widget, event) -> bool:
        # Only intercept when tmux mouse mode is off. With mouse mode on
        # we let VTE forward the event to tmux, which handles wheel +
        # scroll-while-select natively.
        if not self._intercept_scroll:
            return False
        direction = event.direction
        if direction == Gdk.ScrollDirection.SMOOTH:
            # Touchpads and Wayland mice send smooth scroll. Accumulate
            # delta_y and step by lines once we cross a threshold.
            self._smooth_accum += event.delta_y
            if self._smooth_accum <= -1.0:
                self._smooth_accum = 0.0
                return self._scroll_up()
            if self._smooth_accum >= 1.0:
                self._smooth_accum = 0.0
                return self._scroll_down()
            return True
        if direction == Gdk.ScrollDirection.UP:
            return self._scroll_up()
        if direction == Gdk.ScrollDirection.DOWN:
            return self._scroll_down()
        return False

    def _scroll_up(self) -> bool:
        try:
            return tmux_adapter.enter_copy_mode_up(self._session)
        except tmux_adapter.TmuxError:
            return False

    def _scroll_down(self) -> bool:
        try:
            return tmux_adapter.scroll_copy_mode_down(self._session)
        except tmux_adapter.TmuxError:
            return False

    def _add_link_matcher(self) -> None:
        """Let VTE underline links and show a pointer on hover.

        This only ever matches within one VTE row (plus soft-wrapped
        continuations), which covers a full-width pane. Split panes are
        handled at click time by asking tmux -- see _link_at_event.
        """
        try:
            regex = Vte.Regex.new_for_match(
                links.VTE_PATTERN,
                -1,
                links.PCRE2_MULTILINE | links.PCRE2_CASELESS,
            )
            tag = self._vte.match_add_regex(regex, 0)
            self._vte.match_set_cursor_name(tag, "pointer")
        except (AttributeError, TypeError, GLib.Error):
            # Hover decoration is a nicety; the context menu is the
            # feature. An old or differently-built VTE loses only this.
            pass

    def _link_at_event(self, event) -> str | None:
        """Best-effort URL under the pointer, or None.

        Three sources, most trustworthy first: an explicit OSC 8
        hyperlink, then tmux (which knows where it wrapped a line, and
        which pane owns the cell), then VTE's own matcher as a fallback
        for anything tmux would not answer for.
        """
        try:
            uri = self._vte.hyperlink_check_event(event)
            if uri:
                return uri
        except (AttributeError, TypeError):
            pass

        char_w = self._vte.get_char_width() or 1
        char_h = self._vte.get_char_height() or 1
        col = int(event.x // char_w)
        row = int(event.y // char_h)
        try:
            found = tmux_adapter.url_at_cell(
                self._session, col, row, self._dest
            )
            if found:
                return found
        except tmux_adapter.TmuxError:
            pass

        try:
            match = self._vte.match_check_event(event)
            if match and match[0]:
                return match[0]
        except (AttributeError, TypeError):
            pass
        return None

    def _open_url(self, url: str) -> None:
        url = links.normalize(url)
        if not links.is_openable(url):
            return
        try:
            Gtk.show_uri_on_window(
                self.get_toplevel(), url, Gdk.CURRENT_TIME
            )
        except GLib.Error:
            pass

    def _on_button_press(self, _widget, event) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button != Gdk.BUTTON_SECONDARY:
            return False
        self._show_context_menu(event)
        return True

    def _show_context_menu(self, event) -> None:
        menu = Gtk.Menu()

        url = self._link_at_event(event)
        if url and links.is_openable(links.normalize(url)):
            shown = url if len(url) <= 48 else url[:45] + "\u2026"
            open_item = Gtk.MenuItem(label=f"Open {shown}")
            open_item.connect("activate", lambda *_: self._open_url(url))
            menu.append(open_item)

            copy_link = Gtk.MenuItem(label="Copy Link Address")
            copy_link.connect(
                "activate",
                lambda *_: (
                    _write_clipboard_text(Gdk.SELECTION_CLIPBOARD, url),
                    _write_clipboard_text(Gdk.SELECTION_PRIMARY, url),
                ),
            )
            menu.append(copy_link)
            menu.append(Gtk.SeparatorMenuItem())

        copy_item = Gtk.MenuItem(label="Copy")
        # In tmux selection mode the selection lives in a tmux buffer,
        # not in VTE — so we can't reliably know if there's something to
        # copy until we ask tmux. Keep it enabled in that mode.
        copy_item.set_sensitive(
            self._vte.get_has_selection() or not self._intercept_scroll
        )
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
        if self._vte.get_has_selection():
            self._vte.copy_clipboard_format(Vte.Format.TEXT)
            text = _read_clipboard_text(Gdk.SELECTION_CLIPBOARD)
            if text is not None:
                _write_clipboard_text(Gdk.SELECTION_PRIMARY, text)
            return
        # tmux selection mode: pull the most recent tmux buffer.
        text = tmux_adapter.show_buffer()
        if not text:
            return
        _write_clipboard_text(Gdk.SELECTION_CLIPBOARD, text)
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
