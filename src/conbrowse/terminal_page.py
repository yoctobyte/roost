import shutil
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import GLib, Gtk, Vte  # noqa: E402


class TerminalPage(Gtk.Box):
    def __init__(
        self,
        session: str,
        on_child_exited: Callable[[int], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_child_exited = on_child_exited

        self._vte = Vte.Terminal()
        self._vte.set_scrollback_lines(10000)
        self._vte.set_mouse_autohide(True)

        self.pack_start(self._vte, True, True, 0)

        tmux_bin = shutil.which("tmux") or "/usr/bin/tmux"
        self._vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,  # working dir
            [tmux_bin, "attach", "-t", f"={session}"],
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

    def grab_focus(self) -> None:  # type: ignore[override]
        self._vte.grab_focus()

    def _on_spawn_ready(self, _terminal, _pid, error, _user_data) -> None:
        if error is not None:
            self._on_child_exited(-1)

    def _handle_child_exited(self, _terminal, status: int) -> None:
        self._on_child_exited(status)
