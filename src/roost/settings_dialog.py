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

        box = self.get_content_area()
        box.set_spacing(12)
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

        self.show_all()

    def get_settings(self) -> Settings:
        theme_key = next(
            (k for k, b in self._theme_buttons.items() if b.get_active()),
            next(iter(self._theme_buttons)),
        )
        return Settings(
            overview_font_size=int(self._font_spin.get_value()),
            theme=theme_key,
        ).clamp()


def _label(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(0.0)
    return lbl
