import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk  # noqa: E402

from conbrowse.controller import Controller
from conbrowse.models import AppState
from conbrowse.overview_page import OverviewPage
from conbrowse.terminal_page import TerminalPage

_OVERVIEW_PAGE = 0
_TERMINAL_PAGE = 1


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, controller: Controller) -> None:
        super().__init__(application=app, title="conbrowse")
        self.set_default_size(1100, 750)

        self._controller = controller
        self._suppress_tab_switch = False
        self._session_lost_shown = False

        self._build_header()
        self._build_body()
        self._build_accelerators()

        controller.on_state_changed(self._on_state_changed)
        controller.on_error(self._on_error)

        self.connect("destroy", self._on_destroy)

    # -- build ------------------------------------------------------------

    def _build_header(self) -> None:
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("conbrowse")
        header.set_subtitle(self._controller.session)
        self.set_titlebar(header)

        self._btn_new = _hbtn("document-new-symbolic", "New console", self._action_new)
        header.pack_start(self._btn_new)

        self._btn_overview = _hbtn(
            "view-grid-symbolic", "Show overview", self._action_overview
        )
        header.pack_start(self._btn_overview)

        self._btn_rename = _hbtn(
            "document-edit-symbolic", "Rename current", self._action_rename
        )
        header.pack_end(self._btn_rename)

        self._btn_close = _hbtn(
            "window-close-symbolic", "Close current", self._action_close
        )
        header.pack_end(self._btn_close)

        self._btn_refresh = _hbtn(
            "view-refresh-symbolic", "Refresh", self._action_refresh
        )
        header.pack_end(self._btn_refresh)

    def _build_body(self) -> None:
        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        self.add(self._notebook)

        self._overview = OverviewPage(self._on_card_activated)
        self._notebook.append_page(self._overview, Gtk.Label(label="Overview"))

        self._terminal = TerminalPage(
            session=self._controller.session,
            on_child_exited=self._on_terminal_child_exited,
        )
        self._terminal_label = Gtk.Label(label="Console")
        self._notebook.append_page(self._terminal, self._terminal_label)

        self._notebook.connect("switch-page", self._on_page_switched)

    def _build_accelerators(self) -> None:
        group = Gtk.AccelGroup()
        self.add_accel_group(group)

        def bind(keyval, mods, handler):
            group.connect(keyval, mods, Gtk.AccelFlags.VISIBLE, handler)

        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        bind(Gdk.KEY_T, ctrl_shift, lambda *_: (self._action_new(), True)[1])
        bind(Gdk.KEY_W, ctrl_shift, lambda *_: (self._action_close(), True)[1])
        bind(Gdk.KEY_R, ctrl_shift, lambda *_: (self._action_rename(), True)[1])
        bind(Gdk.KEY_O, ctrl_shift, lambda *_: (self._action_overview(), True)[1])
        bind(
            Gdk.KEY_F5,
            Gdk.ModifierType(0),
            lambda *_: (self._action_refresh(), True)[1],
        )

    # -- actions ----------------------------------------------------------

    def _action_new(self) -> None:
        self._controller.new_console()
        self._notebook.set_current_page(_TERMINAL_PAGE)

    def _action_overview(self) -> None:
        self._notebook.set_current_page(_OVERVIEW_PAGE)

    def _action_refresh(self) -> None:
        self._controller.sync_now()

    def _action_rename(self) -> None:
        win = self._controller.selected_window()
        if win is None:
            return
        new = _prompt(self, "Rename console", "New name:", win.name)
        if new is None or not new.strip():
            return
        self._controller.rename_console(win.id, new.strip())

    def _action_close(self) -> None:
        win = self._controller.selected_window()
        if win is None:
            return
        self._controller.close_console(win.id)
        self._notebook.set_current_page(_OVERVIEW_PAGE)

    # -- events -----------------------------------------------------------

    def _on_card_activated(self, window_id: str) -> None:
        self._controller.select(window_id)
        self._notebook.set_current_page(_TERMINAL_PAGE)
        self._terminal.grab_focus()

    def _on_page_switched(self, _notebook, _page, page_num: int) -> None:
        if self._suppress_tab_switch:
            return
        if page_num == _OVERVIEW_PAGE:
            self._controller.clear_selection()
        else:
            self._terminal.grab_focus()

    def _on_state_changed(self, state: AppState) -> None:
        self._overview.set_state(state)
        win = state.by_id(state.selected_id) if state.selected_id else None
        self._terminal_label.set_text(win.name if win else "Console")

    def _on_error(self, message: str) -> None:
        if "no server" in message or "can't find session" in message:
            self._show_session_lost()
            return
        _toast(self, message)

    def _on_terminal_child_exited(self, _status: int) -> None:
        self._show_session_lost()

    def _show_session_lost(self) -> None:
        if self._session_lost_shown:
            return
        self._session_lost_shown = True
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="tmux session lost",
            secondary_text=(
                f"The managed tmux session '{self._controller.session}' "
                "is no longer reachable. It will not be recreated "
                "automatically."
            ),
        )
        dialog.add_button("Quit", Gtk.ResponseType.CLOSE)
        dialog.run()
        dialog.destroy()
        self.destroy()

    def _on_destroy(self, _widget) -> None:
        self._controller.stop()


def _hbtn(icon_name: str, tooltip: str, handler) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_tooltip_text(tooltip)
    btn.connect("clicked", lambda *_: handler())
    return btn


def _prompt(parent: Gtk.Window, title: str, prompt: str, initial: str) -> str | None:
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("OK", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label=prompt, xalign=0.0))
    entry = Gtk.Entry()
    entry.set_text(initial)
    entry.set_activates_default(True)
    box.add(entry)
    dialog.show_all()
    response = dialog.run()
    value = entry.get_text() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    return value


def _toast(parent: Gtk.Window, message: str) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text="conbrowse error",
        secondary_text=message,
    )
    dialog.run()
    dialog.destroy()
