import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from roost import settings as settings_module
from roost import tmux_adapter
from roost.config import TAB_LABEL_MAX_CHARS, TAB_STRIP_MULTIROW
from roost.controller import Controller
from roost.models import AppState, WindowInfo
from roost.overview_page import OverviewPage
from roost.settings import Settings
from roost.settings_dialog import SettingsDialog
from roost.terminal_page import TerminalPage

_STACK_OVERVIEW = "overview"
_STACK_TERMINAL = "terminal"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, controller: Controller) -> None:
        super().__init__(application=app, title="roost")
        self.set_default_size(1100, 750)

        self._controller = controller
        self._settings: Settings = settings_module.load()
        self._session_lost_shown = False
        self._window_buttons: dict[str, Gtk.ToggleButton] = {}
        self._updating_buttons = False

        self._build_header()
        self._build_body()
        self._build_accelerators()

        controller.on_state_changed(self._on_state_changed)
        controller.on_error(self._on_error)

        # When the main window regains focus and the terminal page is
        # visible, forward focus to the VTE so function keys land there.
        self.connect("focus-in-event", self._on_window_focus_in)

        self._on_state_changed(controller.state)

        self.connect("destroy", self._on_destroy)

    # -- build ------------------------------------------------------------

    def _build_header(self) -> None:
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("roost")
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

        self._btn_prefs = _hbtn(
            "preferences-system-symbolic",
            "Preferences",
            self._action_preferences,
        )
        header.pack_end(self._btn_prefs)

    def _build_body(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        if TAB_STRIP_MULTIROW:
            self._tab_strip: Gtk.Container = Gtk.FlowBox()
            self._tab_strip.set_selection_mode(Gtk.SelectionMode.NONE)
            self._tab_strip.set_homogeneous(False)
            self._tab_strip.set_max_children_per_line(64)
            self._tab_strip.set_min_children_per_line(1)
            self._tab_strip.set_row_spacing(2)
            self._tab_strip.set_column_spacing(2)
            self._tab_strip.set_margin_top(4)
            self._tab_strip.set_margin_bottom(4)
            self._tab_strip.set_margin_start(6)
            self._tab_strip.set_margin_end(6)
            outer.pack_start(self._tab_strip, False, False, 0)
        else:
            self._tab_strip = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=2
            )
            self._tab_strip.set_margin_top(4)
            self._tab_strip.set_margin_bottom(4)
            self._tab_strip.set_margin_start(6)
            self._tab_strip.set_margin_end(6)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
            scrolled.add(self._tab_strip)
            outer.pack_start(scrolled, False, False, 0)

        outer.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )

        self._overview_button = Gtk.ToggleButton(label="Overview")
        self._overview_button.set_tooltip_text("Show overview of all consoles")
        self._overview_button.set_can_focus(False)
        self._overview_button.connect(
            "toggled", self._on_overview_button_toggled
        )
        self._tab_strip.add(self._overview_button)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        outer.pack_start(self._stack, True, True, 0)

        self._overview = OverviewPage(self._on_card_activated, self._settings)
        self._stack.add_named(self._overview, _STACK_OVERVIEW)

        self._terminal = TerminalPage(
            session=self._controller.session,
            on_child_exited=self._on_terminal_child_exited,
        )
        theme = self._settings.theme_obj()
        self._terminal.apply_theme(theme.fg, theme.bg)
        self._stack.add_named(self._terminal, _STACK_TERMINAL)

        self._show_overview()

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
        self._show_terminal()

    def _action_overview(self) -> None:
        self._controller.clear_selection()
        self._show_overview()

    def _action_refresh(self) -> None:
        self._controller.sync_now()

    def _action_preferences(self) -> None:
        dialog = SettingsDialog(self, self._settings)
        try:
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                new = dialog.get_settings()
                self._settings = new
                settings_module.save(new)
                self._apply_settings()
        finally:
            dialog.destroy()

    def _apply_settings(self) -> None:
        self._overview.apply_settings(self._settings)
        theme = self._settings.theme_obj()
        self._terminal.apply_theme(theme.fg, theme.bg)

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
        self._show_overview()

    # -- events -----------------------------------------------------------

    def _on_card_activated(self, window_id: str) -> None:
        self._controller.select(window_id)
        self._show_terminal()

    def _on_overview_button_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_buttons:
            return
        if button.get_active():
            self._controller.clear_selection()
            self._show_overview()
        else:
            # Re-assert overview toggle if user is clicking it off without
            # selecting a window tab.
            if self._controller.state.selected_id is None:
                self._updating_buttons = True
                button.set_active(True)
                self._updating_buttons = False

    def _on_window_button_toggled(
        self, button: Gtk.ToggleButton, window_id: str
    ) -> None:
        if self._updating_buttons:
            return
        if button.get_active():
            self._controller.select(window_id)
            self._show_terminal()

    def _on_state_changed(self, state: AppState) -> None:
        self._overview.set_state(state)
        self._rebuild_window_buttons(state)
        selected = state.by_id(state.selected_id) if state.selected_id else None
        self._sync_button_state(selected)
        if selected is None:
            self._show_overview()

    def _rebuild_window_buttons(self, state: AppState) -> None:
        seen: set[str] = set()
        for win in state.windows:
            seen.add(win.id)
            btn = self._window_buttons.get(win.id)
            label = f"{win.index}: {win.name}"
            tooltip = _format_tooltip(win)
            if btn is None:
                btn = Gtk.ToggleButton(label=label)
                btn.set_can_focus(False)
                btn.connect("toggled", self._on_window_button_toggled, win.id)
                inner = btn.get_child()
                if isinstance(inner, Gtk.Label):
                    inner.set_ellipsize(Pango.EllipsizeMode.END)
                    inner.set_max_width_chars(TAB_LABEL_MAX_CHARS)
                self._tab_strip.add(btn)
                self._window_buttons[win.id] = btn
            else:
                inner = btn.get_child()
                if isinstance(inner, Gtk.Label):
                    inner.set_text(label)
            btn.set_tooltip_text(tooltip)
        for stale in list(self._window_buttons):
            if stale in seen:
                continue
            btn = self._window_buttons.pop(stale)
            parent = btn.get_parent()
            if parent is not None:
                parent.destroy()
        self._tab_strip.show_all()

    def _sync_button_state(self, selected: WindowInfo | None) -> None:
        self._updating_buttons = True
        try:
            self._overview_button.set_active(selected is None)
            for wid, btn in self._window_buttons.items():
                btn.set_active(selected is not None and wid == selected.id)
        finally:
            self._updating_buttons = False

    def _show_overview(self) -> None:
        self._stack.set_visible_child_name(_STACK_OVERVIEW)
        self._updating_buttons = True
        self._overview_button.set_active(True)
        for btn in self._window_buttons.values():
            btn.set_active(False)
        self._updating_buttons = False

    def _show_terminal(self) -> None:
        self._stack.set_visible_child_name(_STACK_TERMINAL)
        self._terminal.grab_focus()

    def _on_error(self, message: str) -> None:
        if "no server" in message or "can't find session" in message:
            self._show_session_lost()
            return
        _toast(self, message)

    def _on_terminal_child_exited(self, _status: int) -> None:
        # The VTE child (our `tmux attach` client) also exits during a
        # normal window close — ask tmux whether the session is actually
        # gone before alarming the user.
        try:
            if tmux_adapter.session_exists(self._controller.session):
                return
        except Exception:
            pass
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

    def _on_window_focus_in(self, _widget, _event) -> bool:
        if self._stack.get_visible_child_name() == _STACK_TERMINAL:
            self._terminal.grab_focus()
        return False

    def _on_destroy(self, _widget) -> None:
        self._controller.stop()


def _format_tooltip(win: WindowInfo) -> str:
    lines = [f"{win.index}: {win.name}"]
    if win.current_command:
        lines.append(f"cmd: {win.current_command}")
    if win.current_path:
        lines.append(f"cwd: {win.current_path}")
    if win.preview:
        preview_lines = [
            ln for ln in win.preview.splitlines() if ln.strip()
        ][-6:]
        if preview_lines:
            lines.append("")
            lines.extend(preview_lines)
    return "\n".join(lines)


def _hbtn(icon_name: str, tooltip: str, handler) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_tooltip_text(tooltip)
    btn.set_can_focus(False)
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
        text="roost error",
        secondary_text=message,
    )
    dialog.run()
    dialog.destroy()
