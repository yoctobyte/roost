import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import Gtk  # noqa: E402

from conbrowse.config import APP_ID  # noqa: E402
from conbrowse.controller import Controller  # noqa: E402
from conbrowse.tmux_adapter import TmuxError  # noqa: E402


class ConbrowseApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self._window: Gtk.ApplicationWindow | None = None
        self._controller: Controller | None = None

    def do_activate(self) -> None:  # type: ignore[override]
        if self._window is None:
            from conbrowse.main_window import MainWindow

            self._controller = Controller()
            try:
                self._controller.start()
            except TmuxError as exc:
                self._fatal(f"Failed to start tmux session: {exc}")
                return
            self._window = MainWindow(self, self._controller)
        self._window.present()

    def _fatal(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="conbrowse cannot start",
            secondary_text=message,
        )
        dialog.run()
        dialog.destroy()
        self.quit()


def main() -> int:
    app = ConbrowseApp()
    return app.run(sys.argv)
