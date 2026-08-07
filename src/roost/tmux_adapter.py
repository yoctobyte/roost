import subprocess
from dataclasses import replace

from roost.models import WindowInfo


class TmuxError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        super().__init__(
            f"tmux {' '.join(args)!r} failed ({returncode}): {stderr.strip()}"
        )
        self.args = args
        self.returncode = returncode
        self.stderr = stderr


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise TmuxError(args, proc.returncode, proc.stderr)
    return proc.stdout


def session_exists(name: str) -> bool:
    try:
        _run(["has-session", "-t", f"={name}"])
        return True
    except TmuxError:
        return False


def ensure_session(name: str) -> bool:
    """Create the session if missing. Returns True if it was created."""
    created = False
    if not session_exists(name):
        _run(["new-session", "-d", "-s", name])
        created = True
    return created


def set_mouse_mode(session: str, on: bool) -> None:
    """Toggle tmux session-scoped mouse mode.

    With mouse on, tmux owns drag selection and the wheel scrolls
    natively into copy-mode (and selection survives across pages).
    With mouse off, VTE owns selection and roost forwards wheel events
    via copy-mode itself.

    When turning mouse on we also rebind MouseDragEnd1Pane to
    `copy-selection-no-clear` so the highlight stays visible after
    button release. The default binding is `copy-pipe-and-cancel`,
    which exits copy-mode on release and visually clears the selection
    (the text is still in a buffer, but the user has no idea what they
    selected). This rebind is server-global; we leave it in place even
    after switching back to vte mode because it only fires during a
    mouse drag — which never happens when mouse mode is off.
    """
    try:
        _run(["set-option", "-t", session, "mouse", "on" if on else "off"])
    except TmuxError:
        pass
    if on:
        for table in ("copy-mode", "copy-mode-vi"):
            try:
                _run(
                    [
                        "bind-key",
                        "-T",
                        table,
                        "MouseDragEnd1Pane",
                        "send-keys",
                        "-X",
                        "copy-selection-no-clear",
                    ]
                )
            except TmuxError:
                pass


def show_buffer() -> str:
    """Return the most recent tmux buffer text, or empty string."""
    try:
        return _run(["show-buffer"])
    except TmuxError:
        return ""


_LIST_FMT = (
    "#{window_id}\t#{window_index}\t#{window_name}\t#{window_active}\t"
    "#{pane_current_command}\t#{pane_current_path}\t#{pane_pid}"
)


def list_windows(session: str) -> list[WindowInfo]:
    out = _run(["list-windows", "-t", f"={session}", "-F", _LIST_FMT])
    result: list[WindowInfo] = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        wid, idx, name, active, cmd, path, pid_s = parts[:7]
        try:
            pane_pid = int(pid_s)
        except ValueError:
            pane_pid = 0
        last_cmd = foreground_command(pane_pid) if pane_pid else ""
        result.append(
            WindowInfo(
                id=wid,
                index=int(idx),
                name=name,
                active=(active == "1"),
                current_command=cmd,
                current_path=path,
                last_command=last_cmd,
                pane_pid=pane_pid,
            )
        )
    return result


def foreground_command(pane_pid: int) -> str:
    """Return the full argv of the pane's foreground process, or "".

    Uses /proc/<pane_pid>/stat's tpgid field (the controlling terminal's
    foreground process-group id). When tpgid equals the shell's own pid
    the pane is idle at a prompt and we return "". Otherwise we read
    /proc/<tpgid>/cmdline — the group leader usually *is* a process,
    which gives us the command line with arguments (e.g. "vim src/x.py").
    """
    try:
        with open(f"/proc/{pane_pid}/stat", "rb") as fh:
            data = fh.read()
    except OSError:
        return ""
    # Skip the comm field which is in parens and may contain spaces.
    rparen = data.rfind(b")")
    if rparen < 0:
        return ""
    tail = data[rparen + 2 :].split()
    # After ')': state, ppid, pgrp, session, tty_nr, tpgid -> index 5.
    if len(tail) < 6:
        return ""
    try:
        tpgid = int(tail[5])
    except ValueError:
        return ""
    if tpgid <= 0 or tpgid == pane_pid:
        return ""
    try:
        with open(f"/proc/{tpgid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    parts = [p.decode("utf-8", "replace") for p in raw.split(b"\x00") if p]
    if not parts:
        return ""
    return " ".join(parts)


def process_starttime(pid: int) -> int:
    """Return /proc/<pid>/stat field 22 (starttime, clock ticks since boot).

    Smaller values are older processes. Returns 0 if unreadable, which
    sorts as oldest — fine, since we only care about a stable ordering.
    """
    if pid <= 0:
        return 0
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
    except OSError:
        return 0
    rparen = data.rfind(b")")
    if rparen < 0:
        return 0
    tail = data[rparen + 2 :].split()
    if len(tail) < 20:
        return 0
    try:
        return int(tail[19])
    except ValueError:
        return 0


def capture_preview(window_id: str, lines: int) -> str:
    try:
        out = _run(
            [
                "capture-pane",
                "-p",
                "-J",
                "-t",
                window_id,
                "-S",
                f"-{lines}",
            ]
        )
    except TmuxError:
        return ""
    return out.rstrip("\n")


def new_window(
    session: str, name: str | None = None, cwd: str | None = None
) -> str:
    args = ["new-window", "-d", "-t", f"={session}", "-P", "-F", "#{window_id}"]
    if cwd:
        args.extend(["-c", cwd])
    if name:
        args.extend(["-n", name])
    return _run(args).strip()


def send_text(window_id: str, text: str) -> None:
    """Send literal text to a window's foreground pane. No Enter."""
    if not text:
        return
    _run(["send-keys", "-t", window_id, "-l", text])


def enter_copy_mode_up(session: str) -> bool:
    """Enter copy-mode in the session's active pane and scroll up one page.

    Returns True if copy-mode was triggered. Returns False (and does
    nothing) when the active pane is on the alternate screen — i.e. a
    full-screen TUI app like vim/htop/claude is running. Those apps
    own PgUp themselves; intervening leaves the cursor mis-positioned
    after copy-mode exits.
    """
    try:
        out = _run(
            [
                "display-message",
                "-p",
                "-t",
                session,
                "#{alternate_on}",
            ]
        ).strip()
    except TmuxError:
        out = "0"
    if out == "1":
        return False
    _run(["copy-mode", "-u", "-t", session])
    return True


def scroll_copy_mode_down(session: str) -> bool:
    """If the active pane is in copy-mode, scroll it down half a page.

    Returns True if a scroll was sent. Does nothing (and returns False)
    when the pane is on the alternate screen or not in copy-mode.
    """
    try:
        out = _run(
            [
                "display-message",
                "-p",
                "-t",
                session,
                "#{alternate_on} #{pane_in_mode}",
            ]
        ).strip()
    except TmuxError:
        return False
    parts = out.split()
    if len(parts) != 2:
        return False
    alt, in_mode = parts
    if alt == "1" or in_mode != "1":
        return False
    try:
        _run(["send-keys", "-t", session, "-X", "halfpage-down"])
    except TmuxError:
        return False
    return True


def set_status_bar(session: str, on: bool) -> None:
    _run(["set-option", "-t", session, "status", "on" if on else "off"])


def rename_window(window_id: str, name: str) -> None:
    _run(["rename-window", "-t", window_id, name])


def kill_window(window_id: str) -> None:
    _run(["kill-window", "-t", window_id])


def select_window(window_id: str) -> None:
    _run(["select-window", "-t", window_id])


def swap_windows(a: str, b: str) -> None:
    _run(["swap-window", "-s", a, "-t", b])


def list_windows_with_previews(session: str, preview_lines: int) -> list[WindowInfo]:
    windows = list_windows(session)
    return [
        replace(w, preview=capture_preview(w.id, preview_lines)) for w in windows
    ]
