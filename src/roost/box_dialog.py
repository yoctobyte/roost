"""Adding and authorising a box.

Probing a box can take seconds when it is unreachable, so every probe
runs on a worker thread and reports back through GLib.idle_add. The
dialog never blocks and never prompts for a credential itself -- when a
box needs a key, an interactive terminal is handed to the user and ssh
does its own asking.
"""

import shlex
import shutil
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")

from gi.repository import GLib, Gtk, Vte  # noqa: E402

from roost import settings, ssh  # noqa: E402

_STATUS_TEXT = {
    ssh.READY: ("✓", "ready"),
    ssh.NEEDS_KEY: ("!", "needs an ssh key"),
    ssh.OFFLINE: ("×", "offline"),
    ssh.NO_TMUX: ("!", "tmux not installed there"),
}


def status_markup(state: str, detail: str = "") -> str:
    icon, text = _STATUS_TEXT.get(state, ("?", state))
    out = f"{icon} {GLib.markup_escape_text(text)}"
    if detail and state in (ssh.OFFLINE, ssh.NO_TMUX):
        out += f" <small>{GLib.markup_escape_text(detail)}</small>"
    return out


def probe_async(dest: str | None, done: Callable[[str, str], None]) -> None:
    """Probe off the main thread; `done` is called back on the main one."""

    def worker() -> None:
        state, detail = ssh.probe(dest)
        GLib.idle_add(lambda: (done(state, detail), False)[1])

    threading.Thread(target=worker, daemon=True).start()


class AddBoxDialog(Gtk.Dialog):
    """Ask for a destination, probe it, and offer to fix what is wrong."""

    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(
            title="Add a box", transient_for=parent, modal=True
        )
        self.set_default_size(460, -1)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self._add_btn = self.add_button("Add", Gtk.ResponseType.OK)
        self._add_btn.set_sensitive(False)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        for setter in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{setter}")(12)

        box.add(
            _wrapped(
                "Enter an ssh destination — a host alias from your "
                "~/.ssh/config, or user@host. roost will check whether it "
                "can reach the box without a password."
            )
        )

        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("user@host")
        self._entry.set_activates_default(False)
        self._entry.connect("activate", lambda *_: self._check())
        box.add(self._entry)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._check_btn = Gtk.Button(label="Check")
        self._check_btn.connect("clicked", lambda *_: self._check())
        row.pack_start(self._check_btn, False, False, 0)
        self._spinner = Gtk.Spinner()
        row.pack_start(self._spinner, False, False, 0)
        self._status = Gtk.Label(xalign=0.0)
        self._status.set_line_wrap(True)
        row.pack_start(self._status, True, True, 0)
        box.add(row)

        self._fix_btn = Gtk.Button(label="Install ssh key…")
        self._fix_btn.connect("clicked", lambda *_: self._install_key())
        self._fix_btn.set_no_show_all(True)
        box.add(self._fix_btn)

        self._resolved = Gtk.Label(xalign=0.0)
        self._resolved.set_line_wrap(True)
        box.add(self._resolved)

        self.show_all()

    def get_dest(self) -> str:
        return self._entry.get_text().strip()

    def _check(self) -> None:
        dest = self.get_dest()
        if not dest:
            return
        self._fix_btn.hide()
        self._add_btn.set_sensitive(False)
        self._check_btn.set_sensitive(False)
        self._spinner.start()
        self._status.set_markup("<small>checking…</small>")

        # Resolving through ~/.ssh/config needs no connection, so it can
        # be shown immediately -- useful when the destination is an alias.
        info = ssh.resolve(dest)
        if info.get("hostname"):
            user = info.get("user", "")
            port = info.get("port", "22")
            suffix = "" if port == "22" else f":{port}"
            who = f"{user}@" if user else ""
            self._resolved.set_markup(
                f"<small>resolves to {GLib.markup_escape_text(who + info['hostname'] + suffix)}</small>"
            )

        probe_async(dest, self._on_probed)

    def _on_probed(self, state: str, detail: str) -> None:
        self._spinner.stop()
        self._check_btn.set_sensitive(True)
        marker = settings.host_marker(self.get_dest())
        text = status_markup(state, detail)
        if state == ssh.READY and marker:
            # Say up front how this box's tabs will be marked, since the
            # mark is the only thing telling them apart from local ones.
            text += (
                f"  <small>tabs marked "
                f"<b>{GLib.markup_escape_text(marker)}</b></small>"
            )
        self._status.set_markup(text)
        # A box that is merely offline is still worth adding -- it may
        # be a laptop that is usually shut. Only a missing key has a fix
        # to offer here.
        self._add_btn.set_sensitive(state != ssh.NEEDS_KEY)
        if state == ssh.NEEDS_KEY:
            self._fix_btn.show()

    def _install_key(self) -> None:
        dest = self.get_dest()
        if not dest:
            return
        dialog = KeyInstallDialog(self, dest)
        try:
            dialog.run()
        finally:
            dialog.destroy()
        self._check()


class KeyInstallDialog(Gtk.Dialog):
    """A real terminal running ssh-copy-id, so ssh does its own asking."""

    def __init__(self, parent: Gtk.Window, dest: str) -> None:
        super().__init__(
            title=f"Install ssh key on {dest}",
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(680, 420)
        self._close_btn = self.add_button("Close", Gtk.ResponseType.CLOSE)

        box = self.get_content_area()
        box.set_spacing(8)
        for setter in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{setter}")(12)
        box.add(
            _wrapped(
                "This runs ssh-copy-id in a terminal below. Type the "
                "box's password when asked — roost never sees it. If you "
                "have no ssh key yet, one is created first."
            )
        )

        self._vte = Vte.Terminal()
        self._vte.set_scrollback_lines(2000)
        box.pack_start(self._vte, True, True, 0)

        shell = shutil.which("bash") or "/bin/sh"
        self._vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,
            [shell, "-c", ssh.key_install_command(dest)],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            self._on_spawned,
            None,
        )
        self._vte.connect("child-exited", self._on_exited)
        self.show_all()
        self._vte.grab_focus()

    def _on_spawned(self, _terminal, _pid, error, _data) -> None:
        if error is not None:
            self._vte.feed(
                f"\r\ncould not start: {error}\r\n".encode()
            )

    def _on_exited(self, _terminal, status: int) -> None:
        note = "done — closing is safe" if status == 0 else "did not finish"
        self._vte.feed(f"\r\n[{note}]\r\n".encode())
        self._close_btn.grab_focus()


def _wrapped(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0.0)
    label.set_line_wrap(True)
    label.set_max_width_chars(56)
    return label
