import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import Gtk  # noqa: E402

from conbrowse.config import APP_ID  # noqa: E402


class ConbrowseApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self._window: Gtk.ApplicationWindow | None = None

    def do_activate(self) -> None:  # type: ignore[override]
        if self._window is None:
            from conbrowse.main_window import MainWindow

            self._window = MainWindow(self)
        self._window.present()


def main() -> int:
    app = ConbrowseApp()
    return app.run(sys.argv)
