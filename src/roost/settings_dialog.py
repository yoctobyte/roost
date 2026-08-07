import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402

from roost import box_dialog  # noqa: E402
from roost.settings import (
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    Settings,
    THEMES,
)


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, current: Settings) -> None:
        super().__init__(title="Preferences", transient_for=parent, modal=True)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(520, -1)

        self._current = current

        box = self.get_content_area()
        box.set_spacing(14)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(16)
        box.set_margin_end(16)

        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(12)
        box.add(grid)

        grid.attach(_label("Overview font size (pt):"), 0, 0, 1, 1)
        self._font_spin = Gtk.SpinButton.new_with_range(
            MIN_FONT_SIZE, MAX_FONT_SIZE, 1
        )
        self._font_spin.set_value(current.overview_font_size)
        grid.attach(self._font_spin, 1, 0, 1, 1)

        grid.attach(_label("Theme:"), 0, 1, 1, 1)
        theme_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        grid.attach(theme_box, 1, 1, 1, 1)

        self._theme_buttons: dict[str, Gtk.RadioButton] = {}
        first: Gtk.RadioButton | None = None
        for key, theme in THEMES.items():
            btn = Gtk.RadioButton.new_with_label_from_widget(first, theme.name)
            if first is None:
                first = btn
            if current.theme == key:
                btn.set_active(True)
            self._theme_buttons[key] = btn
            theme_box.pack_start(btn, False, False, 0)

        self._fix_contrast_check = Gtk.CheckButton(
            label="Fix unreadable colors"
        )
        self._fix_contrast_check.set_active(current.fix_contrast)
        box.add(self._fix_contrast_check)

        contrast_explain = Gtk.Label(xalign=0.0)
        contrast_explain.set_line_wrap(True)
        contrast_explain.set_max_width_chars(60)
        contrast_explain.set_markup(
            "<small>"
            "Programs pick colors assuming a black background, so some "
            "of them vanish on other themes (dark blue on brown, bright "
            "yellow on cream). When on, such colors are lightened or "
            "darkened just enough to stay readable, keeping their hue. "
            "Turn off for exact ANSI colors."
            "</small>"
        )
        box.add(contrast_explain)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        boxes_section = Gtk.Label(xalign=0.0)
        boxes_section.set_markup("<b>Boxes</b>")
        box.add(boxes_section)

        boxes_explain = Gtk.Label(xalign=0.0)
        boxes_explain.set_line_wrap(True)
        boxes_explain.set_max_width_chars(60)
        boxes_explain.set_markup(
            "<small>"
            "Other machines to watch, reached over ssh. Each box shows "
            "the tmux sessions belonging to the user roost connects as, "
            "whoever started them. Boxes are never modified on connect "
            "— roost only lists what is already there."
            "</small>"
        )
        box.add(boxes_explain)

        self._boxes: list[str] = list(current.boxes)
        self._boxes_list = Gtk.ListBox()
        self._boxes_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        boxes_frame = Gtk.Frame()
        boxes_frame.add(self._boxes_list)
        box.add(boxes_frame)

        boxes_buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6
        )
        add_box_btn = Gtk.Button(label="Add box…")
        add_box_btn.connect("clicked", lambda *_: self._on_add_box())
        boxes_buttons.pack_start(add_box_btn, False, False, 0)
        self._remove_box_btn = Gtk.Button(label="Remove")
        self._remove_box_btn.connect("clicked", lambda *_: self._on_remove_box())
        boxes_buttons.pack_start(self._remove_box_btn, False, False, 0)
        box.add(boxes_buttons)

        self._rebuild_boxes()

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        color_section = Gtk.Label(xalign=0.0)
        color_section.set_markup("<b>Tab colors</b>")
        box.add(color_section)

        self._auto_color_check = Gtk.CheckButton(
            label="Automatically color tabs by working folder"
        )
        self._auto_color_check.set_active(current.auto_color_tabs)
        box.add(self._auto_color_check)

        color_explain = Gtk.Label(xalign=0.0)
        color_explain.set_line_wrap(True)
        color_explain.set_max_width_chars(60)
        color_explain.set_markup(
            "<small>"
            "When on, each tab gets a pastel color derived from its "
            "project root (for example <tt>~/projects/foo</tt> and "
            "<tt>~/projects/bar</tt> get different colors; "
            "<tt>~/projects/foo/src</tt> inherits <tt>~/projects/foo</tt>). "
            "Right-click a tab and pick <i>Color folder</i> to override. "
            "Explicit choices always win over the automatic color."
            "</small>"
        )
        box.add(color_explain)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        status_section = Gtk.Label(xalign=0.0)
        status_section.set_markup("<b>tmux status bar</b>")
        box.add(status_section)

        self._status_bar_check = Gtk.CheckButton(
            label="Show the green tmux status bar at the bottom"
        )
        self._status_bar_check.set_active(current.show_status_bar)
        box.add(self._status_bar_check)

        status_explain = Gtk.Label(xalign=0.0)
        status_explain.set_line_wrap(True)
        status_explain.set_max_width_chars(60)
        status_explain.set_markup(
            "<small>"
            "tmux normally draws a status line along the bottom of the "
            "pane listing its windows. roost already shows that "
            "information in its own tab strip, so the status bar is "
            "off by default — turning it off frees one row of terminal "
            "real estate. Enable it if you rely on tmux's own indicators "
            "(activity flags, prefix-key feedback, etc.)."
            "</small>"
        )
        box.add(status_explain)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        mouse_section = Gtk.Label(xalign=0.0)
        mouse_section.set_markup("<b>Mouse mode</b>")
        box.add(mouse_section)

        self._mouse_vte = Gtk.RadioButton.new_with_label_from_widget(
            None, "VTE selection (recommended)"
        )
        self._mouse_tmux = Gtk.RadioButton.new_with_label_from_widget(
            self._mouse_vte, "tmux selection (scroll while selecting)"
        )
        if current.mouse_mode == "tmux":
            self._mouse_tmux.set_active(True)
        else:
            self._mouse_vte.set_active(True)
        box.add(self._mouse_vte)
        box.add(self._mouse_tmux)

        mouse_explain = Gtk.Label(xalign=0.0)
        mouse_explain.set_line_wrap(True)
        mouse_explain.set_max_width_chars(60)
        mouse_explain.set_markup(
            "<small>"
            "<b>VTE selection</b> lets you click-drag to select text the "
            "normal way; the selection sticks after you release the mouse "
            "and Ctrl+Shift+C copies it. The wheel scrolls back through "
            "tmux history.\n\n"
            "<b>tmux selection</b> hands the mouse to tmux, which lets you "
            "drag <i>across page boundaries</i> — the selection keeps "
            "growing as you scroll the wheel. Trade-off: tmux owns the "
            "selection, so a plain release no longer leaves a VTE "
            "highlight; copy via the right-click menu instead."
            "</small>"
        )
        box.add(mouse_explain)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        section = Gtk.Label(xalign=0.0)
        section.set_markup("<b>Remember tabs across restarts</b>")
        box.add(section)

        self._remember_check = Gtk.CheckButton(
            label="Save tab names, working directories, and running commands"
        )
        self._remember_check.set_active(current.remember_tabs)
        box.add(self._remember_check)

        explain = Gtk.Label(xalign=0.0)
        explain.set_line_wrap(True)
        explain.set_max_width_chars(60)
        explain.set_markup(
            "<small>"
            "When enabled (default), roost records each tab's name, current "
            "working directory, and the command currently running (when "
            "there is one) to "
            "<tt>~/.local/state/roost/last_session.json</tt>. "
            "After a reboot or crash — when the tmux session has gone — "
            "roost offers a dialog to recreate the tabs you pick. "
            "\n\n"
            "<b>Running commands are never auto-executed.</b> They are "
            "placed on the shell prompt without pressing Enter, so you "
            "review and confirm every one.\n\n"
            "Turn this off if you do not want any session state written "
            "to disk. Delete the file above to clear the saved state."
            "</small>"
        )
        box.add(explain)

        self.show_all()

    def _rebuild_boxes(self) -> None:
        for child in self._boxes_list.get_children():
            self._boxes_list.remove(child)
        # This machine is always watched and cannot be removed, so it is
        # shown for completeness rather than as a configurable entry.
        self._add_box_row(None, "This machine")
        for dest in self._boxes:
            self._add_box_row(dest, dest)
        self._boxes_list.show_all()
        self._remove_box_btn.set_sensitive(bool(self._boxes))

    def _add_box_row(self, dest: str | None, label: str) -> None:
        row = Gtk.ListBoxRow()
        row.dest = dest  # type: ignore[attr-defined]
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for setter in ("top", "bottom", "start", "end"):
            getattr(hb, f"set_margin_{setter}")(6)
        name = Gtk.Label(xalign=0.0, label=label)
        hb.pack_start(name, True, True, 0)
        status = Gtk.Label(xalign=1.0)
        status.set_markup("<small>checking…</small>")
        hb.pack_start(status, False, False, 0)
        row.add(hb)
        self._boxes_list.add(row)

        def done(state: str, detail: str) -> None:
            if status.get_parent() is not None:
                status.set_markup(box_dialog.status_markup(state, detail))

        box_dialog.probe_async(dest, done)

    def _on_add_box(self) -> None:
        dialog = box_dialog.AddBoxDialog(self)
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                dest = dialog.get_dest()
                if dest and dest not in self._boxes:
                    self._boxes.append(dest)
                    self._rebuild_boxes()
        finally:
            dialog.destroy()

    def _on_remove_box(self) -> None:
        row = self._boxes_list.get_selected_row()
        dest = getattr(row, "dest", None) if row is not None else None
        if dest is None:  # "This machine", or nothing selected
            return
        self._boxes = [d for d in self._boxes if d != dest]
        self._rebuild_boxes()

    def get_settings(self) -> Settings:
        theme_key = next(
            (k for k, b in self._theme_buttons.items() if b.get_active()),
            next(iter(self._theme_buttons)),
        )
        return Settings(
            overview_font_size=int(self._font_spin.get_value()),
            theme=theme_key,
            cwd_colors=dict(self._current.cwd_colors),
            auto_color_tabs=self._auto_color_check.get_active(),
            remember_tabs=self._remember_check.get_active(),
            show_status_bar=self._status_bar_check.get_active(),
            sort_kind=self._current.sort_kind,
            mouse_mode="tmux" if self._mouse_tmux.get_active() else "vte",
            fix_contrast=self._fix_contrast_check.get_active(),
            boxes=list(self._boxes),
        ).clamp()


def _label(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(0.0)
    return lbl
