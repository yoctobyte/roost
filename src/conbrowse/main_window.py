import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="conbrowse")
        self.set_default_size(1000, 700)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("conbrowse")
        self.set_titlebar(header)

        placeholder = Gtk.Label(label="conbrowse: scaffold")
        self.add(placeholder)
