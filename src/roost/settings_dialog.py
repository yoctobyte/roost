import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402

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

    def get_settings(self) -> Settings:
        theme_key = next(
            (k for k, b in self._theme_buttons.items() if b.get_active()),
            next(iter(self._theme_buttons)),
        )
        return Settings(
            overview_font_size=int(self._font_spin.get_value()),
            theme=theme_key,
            tab_colors=dict(self._current.tab_colors),
            remember_tabs=self._remember_check.get_active(),
        ).clamp()


def _label(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(0.0)
    return lbl
