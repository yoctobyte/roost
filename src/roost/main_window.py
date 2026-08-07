import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from roost import settings as settings_module
from roost import state as state_module
from roost import tmux_adapter
from roost.config import TAB_LABEL_MAX_CHARS, TAB_STRIP_MULTIROW
from roost.controller import Controller
from roost.models import AppState, WindowInfo
from roost.overview_page import OverviewPage
from roost.restore_dialog import RestoreDialog
from roost.settings import TAB_COLORS, Settings, project_root
from roost.settings_dialog import SettingsDialog
from roost.terminal_page import TerminalPage

_TAB_DND_TARGET = "application/x-roost-tab"

_STACK_OVERVIEW = "overview"
_STACK_TERMINAL = "terminal"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, controller: Controller) -> None:
        super().__init__(application=app, title="roost")
        self.set_default_size(1100, 750)

        self._controller = controller
        self._settings: Settings = settings_module.load()
        self._controller.remember_tabs = self._settings.remember_tabs
        self._apply_status_bar()
        self._session_lost_shown = False
        self._window_buttons: dict[str, Gtk.ToggleButton] = {}
        self._button_css: dict[str, Gtk.CssProvider] = {}
        self._updating_buttons = False
        self._restore_offered = False

        self._build_header()
        self._build_body()
        self._build_accelerators()
        self._apply_mouse_mode()

        controller.on_state_changed(self._on_state_changed)
        controller.on_error(self._on_error)

        # When the main window regains focus and the terminal page is
        # visible, forward focus to the VTE so function keys land there.
        self.connect("focus-in-event", self._on_window_focus_in)

        # Offer a restore dialog once the window is visible and idle.
        GLib.idle_add(self._maybe_offer_restore)

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

        self._btn_sort = _hbtn(
            "view-sort-ascending-symbolic",
            "Sort tabs (right-click for options)",
            self._action_sort,
        )
        self._btn_sort.connect("button-press-event", self._on_sort_button_press)
        header.pack_end(self._btn_sort)

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
        self._terminal.apply_theme(
            theme.fg, theme.bg, self._settings.terminal_palette()
        )
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

    def _action_sort(self) -> None:
        kind = self._settings.sort_kind or settings_module.DEFAULT_SORT_KIND
        self._sort_by(kind)

    def _on_sort_button_press(self, _btn, event) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button != Gdk.BUTTON_SECONDARY:
            return False
        self._show_sort_menu(event)
        return True

    def _show_sort_menu(self, event) -> None:
        menu = Gtk.Menu()
        labels = [
            ("folder", "Sort by project folder"),
            ("name", "Sort by tab name"),
            ("app", "Sort by running command"),
            ("color", "Sort by color tag"),
            ("age", "Sort by age (oldest first)"),
        ]
        current = self._settings.sort_kind or settings_module.DEFAULT_SORT_KIND
        group = None
        for kind, label in labels:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            if group is None:
                group = item
            item.set_active(kind == current)
            item.connect("toggled", self._on_sort_menu_pick, kind)
            menu.append(item)
        menu.show_all()
        menu.attach_to_widget(self._btn_sort, None)
        menu.popup_at_pointer(event)

    def _on_sort_menu_pick(self, item, kind: str) -> None:
        if not item.get_active():
            return
        if kind != self._settings.sort_kind:
            self._settings.sort_kind = kind
            settings_module.save(self._settings)
        self._sort_by(kind)

    def _sort_by(self, kind: str) -> None:
        windows = list(self._controller.state.windows)
        if not windows:
            return
        keyfn = self._sort_keyfn(kind)
        desired = sorted(windows, key=keyfn)
        self._controller.reorder_to([w.id for w in desired])

    def _sort_keyfn(self, kind: str):
        settings = self._settings

        def folder_key(w: WindowInfo):
            return (project_root(w.current_path or "").lower(), w.name.lower())

        if kind == "name":
            return lambda w: (w.name.lower(), w.index)
        if kind == "app":
            return lambda w: (
                (w.current_command or "").lower(),
                w.name.lower(),
            )
        if kind == "color":
            def color_key(w: WindowInfo):
                tc = settings.resolve_tab_color(w.current_path or "")
                return (tc.key if tc is not None else "~", w.name.lower())
            return color_key
        if kind == "age":
            return lambda w: (
                tmux_adapter.process_starttime(w.pane_pid),
                w.name.lower(),
            )
        return folder_key

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
        self._terminal.apply_theme(
            theme.fg, theme.bg, self._settings.terminal_palette()
        )
        self._controller.remember_tabs = self._settings.remember_tabs
        self._apply_status_bar()
        self._apply_mouse_mode()
        self._refresh_all_tab_colors()
        if not self._settings.remember_tabs:
            try:
                state_module.clear()
            except OSError:
                pass

    def _apply_status_bar(self) -> None:
        try:
            tmux_adapter.set_status_bar(
                self._controller.session, self._settings.show_status_bar
            )
        except tmux_adapter.TmuxError:
            pass

    def _apply_mouse_mode(self) -> None:
        on = self._settings.mouse_mode == "tmux"
        try:
            tmux_adapter.set_mouse_mode(self._controller.session, on)
        except tmux_adapter.TmuxError:
            pass
        self._terminal.set_intercept_scroll(not on)

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
        new_ids = [w.id for w in state.windows]
        existing_ids = list(self._window_buttons.keys())
        if new_ids != existing_ids:
            # Order or membership changed (sort, swap, close, new). Tear
            # down and re-add window buttons so visual order matches tmux.
            for btn in list(self._window_buttons.values()):
                parent = btn.get_parent()
                if parent is not None:
                    parent.destroy()
            self._window_buttons.clear()
            self._button_css.clear()
            for win in state.windows:
                btn = self._make_window_button(win)
                self._window_buttons[win.id] = btn
                self._tab_strip.add(btn)
                self._apply_tab_color(btn, win.id, win.current_path)
                btn.set_tooltip_text(_format_tooltip(win))
        else:
            for win in state.windows:
                btn = self._window_buttons[win.id]
                inner = btn.get_child()
                if isinstance(inner, Gtk.Label):
                    inner.set_text(f"{win.index}: {win.name}")
                btn.set_tooltip_text(_format_tooltip(win))
                self._apply_tab_color(btn, win.id, win.current_path)
        self._tab_strip.show_all()

    def _make_window_button(self, win: WindowInfo) -> Gtk.ToggleButton:
        btn = Gtk.ToggleButton(label=f"{win.index}: {win.name}")
        btn.set_can_focus(False)
        btn.connect("toggled", self._on_window_button_toggled, win.id)
        btn.connect("button-press-event", self._on_tab_button_press, win.id)
        inner = btn.get_child()
        if isinstance(inner, Gtk.Label):
            inner.set_ellipsize(Pango.EllipsizeMode.END)
            inner.set_max_width_chars(TAB_LABEL_MAX_CHARS)
        self._install_tab_dnd(btn, win.id)
        return btn

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

    def _apply_tab_color(
        self, btn: Gtk.ToggleButton, window_id: str, cwd: str
    ) -> None:
        color = self._settings.resolve_tab_color(cwd)
        ctx = btn.get_style_context()
        provider = self._button_css.get(window_id)
        if provider is not None:
            ctx.remove_provider(provider)
            self._button_css.pop(window_id, None)
        if color is None:
            return
        bright_bg = _lighten_hex(color.bg, 0.30)
        css = (
            "button {"
            f" background-image: none; background-color: {color.bg};"
            f" color: {color.fg};"
            " border-width: 2px; border-style: solid;"
            f" border-color: {color.bg};"
            "}"
            "button:checked {"
            f" background-image: none; background-color: {bright_bg};"
            f" color: {color.fg};"
            f" border-color: {color.fg};"
            "}"
        ).encode("utf-8")
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._button_css[window_id] = provider

    def _install_tab_dnd(self, btn: Gtk.ToggleButton, window_id: str) -> None:
        targets = Gtk.TargetList.new([])
        targets.add(
            Gdk.Atom.intern(_TAB_DND_TARGET, False),
            Gtk.TargetFlags.SAME_APP,
            0,
        )
        btn.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            [],
            Gdk.DragAction.MOVE,
        )
        btn.drag_source_set_target_list(targets)
        btn.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [],
            Gdk.DragAction.MOVE,
        )
        btn.drag_dest_set_target_list(targets)
        btn.connect("drag-data-get", self._on_tab_drag_data_get, window_id)
        btn.connect(
            "drag-data-received", self._on_tab_drag_data_received, window_id
        )

    def _on_tab_drag_data_get(
        self, _btn, _ctx, data, _info, _time, window_id: str
    ) -> None:
        data.set(data.get_target(), 8, window_id.encode("utf-8"))

    def _on_tab_drag_data_received(
        self, _btn, _ctx, _x, _y, data, _info, _time, target_id: str
    ) -> None:
        raw = data.get_data()
        if not raw:
            return
        source_id = raw.decode("utf-8", "replace")
        if source_id and source_id != target_id:
            self._controller.move_to(source_id, target_id)

    def _on_tab_button_press(self, _btn, event, window_id: str) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button != Gdk.BUTTON_SECONDARY:
            return False
        win = self._controller.state.by_id(window_id)
        if win is None:
            return False
        self._show_tab_menu(event, win)
        return True

    def _show_tab_menu(self, event, win: WindowInfo) -> None:
        menu = Gtk.Menu()

        rename = Gtk.MenuItem(label="Rename…")
        rename.connect("activate", lambda *_: self._tab_rename(win))
        menu.append(rename)

        close = Gtk.MenuItem(label="Close")
        close.connect("activate", lambda *_: self._tab_close(win))
        menu.append(close)

        menu.append(Gtk.SeparatorMenuItem())

        # Color is keyed by the working folder (and its subdirectories),
        # not by the tab name. Apply colors to the project root by
        # default; the user can also bind the exact current cwd.
        color_item = Gtk.MenuItem(label="Color folder")
        color_item.set_submenu(self._build_color_menu(win))
        menu.append(color_item)

        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(event)

    def _build_color_menu(self, win: WindowInfo) -> Gtk.Menu:
        color_menu = Gtk.Menu()

        cwd = win.current_path or ""
        root = project_root(cwd) if cwd else ""
        explicit = self._settings.explicit_color_for(cwd) if cwd else None
        current_prefix = explicit[0] if explicit else None
        current_key = explicit[1] if explicit else None

        # Header: show which path this color will be attached to.
        header_path = root or cwd or "(no folder)"
        header = Gtk.MenuItem(label=f"Apply to: {_short_home(header_path)}")
        header.set_sensitive(False)
        color_menu.append(header)
        color_menu.append(Gtk.SeparatorMenuItem())

        none_item = Gtk.CheckMenuItem(label="None (use auto / inherit)")
        none_item.set_draw_as_radio(True)
        none_item.set_active(current_key is None)
        none_item.connect(
            "activate", lambda *_: self._tab_clear_color(win, current_prefix)
        )
        color_menu.append(none_item)
        color_menu.append(Gtk.SeparatorMenuItem())

        for key, tc in TAB_COLORS.items():
            item = Gtk.CheckMenuItem(label=tc.name)
            item.set_draw_as_radio(True)
            item.set_active(current_key == key)
            item.connect(
                "activate",
                lambda _w, k=key: self._tab_set_color(win, k),
            )
            color_menu.append(item)

        return color_menu

    def _tab_rename(self, win: WindowInfo) -> None:
        new = _prompt(self, "Rename console", "New name:", win.name)
        if new is None or not new.strip():
            return
        self._controller.rename_console(win.id, new.strip())

    def _tab_close(self, win: WindowInfo) -> None:
        self._controller.close_console(win.id)

    def _tab_set_color(self, win: WindowInfo, color_key: str) -> None:
        cwd = win.current_path or ""
        target = project_root(cwd) if cwd else ""
        if not target:
            return
        self._settings.set_cwd_color(target, color_key)
        settings_module.save(self._settings)
        self._refresh_all_tab_colors()

    def _tab_clear_color(
        self, win: WindowInfo, explicit_prefix: str | None
    ) -> None:
        if explicit_prefix:
            self._settings.set_cwd_color(explicit_prefix, None)
            settings_module.save(self._settings)
            self._refresh_all_tab_colors()

    def _refresh_all_tab_colors(self) -> None:
        for wid, btn in self._window_buttons.items():
            w = self._controller.state.by_id(wid)
            if w is None:
                continue
            self._apply_tab_color(btn, wid, w.current_path or "")

    def _on_window_focus_in(self, _widget, _event) -> bool:
        if self._stack.get_visible_child_name() == _STACK_TERMINAL:
            self._terminal.grab_focus()
        return False

    def _maybe_offer_restore(self) -> bool:
        if self._restore_offered:
            return False
        self._restore_offered = True
        try:
            self._offer_restore()
        finally:
            # Whatever happened above, snapshots must start being written
            # again -- the controller holds them back until this point so
            # that startup cannot overwrite the state we just offered.
            self._controller.arm_snapshots()
        return False

    def _offer_restore(self) -> None:
        if not self._controller.was_fresh_start:
            return
        if not self._settings.remember_tabs:
            return
        snap = self._controller.previous_snapshot
        if snap is None or not snap.windows:
            return
        dialog = RestoreDialog(self, snap)
        try:
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                selected = dialog.get_selected()
                if selected:
                    self._controller.restore_windows(selected)
        finally:
            dialog.destroy()

    def _on_destroy(self, _widget) -> None:
        self._controller.stop()


def _format_tooltip(win: WindowInfo) -> str:
    lines = [f"{win.index}: {win.name}"]
    if win.last_command:
        lines.append(f"run: {win.last_command}")
    elif win.current_command:
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


def _short_home(path: str) -> str:
    import os
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


def _lighten_hex(hex_color: str, amount: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


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
