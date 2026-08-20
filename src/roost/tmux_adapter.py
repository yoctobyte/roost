import secrets
import shlex
import subprocess
from dataclasses import replace

from roost import ssh
from roost.models import WindowInfo


class TmuxError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        super().__init__(
            f"tmux {' '.join(args)!r} failed ({returncode}): {stderr.strip()}"
        )
        self.args = args
        self.returncode = returncode
        self.stderr = stderr


def _run(args: list[str], dest: str | None = None) -> str:
    rc, out, err = ssh.run(dest, ["tmux", *args])
    if rc != 0:
        raise TmuxError(args, rc, err)
    return out


def session_exists(name: str, dest: str | None = None) -> bool:
    try:
        _run(["has-session", "-t", f"={name}"], dest)
        return True
    except TmuxError:
        return False


def has_sessions(dest: str | None = None) -> bool:
    """Whether the box has any tmux session at all.

    Never creates one: roost lists what is already there. A box with no
    server running is a box with no sessions, not a failure.
    """
    try:
        out = _run(["list-sessions", "-F", "#{session_name}"], dest)
    except TmuxError:
        return False
    return bool(out.strip())


def create_session(name: str, dest: str | None = None, cwd: str | None = None) -> str:
    """Create a detached session. Only ever called for the user."""
    args = ["new-session", "-d", "-s", name, "-P", "-F", "#{window_id}"]
    if cwd:
        args.extend(["-c", cwd])
    return _run(args, dest).strip()


def set_mouse_mode(session: str, on: bool, dest: str | None = None) -> None:
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
        _run(
            ["set-option", "-t", session, "mouse", "on" if on else "off"],
            dest,
        )
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
                    ],
                    dest,
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
    session: str,
    name: str | None = None,
    cwd: str | None = None,
    dest: str | None = None,
) -> str:
    args = ["new-window", "-d", "-t", f"={session}", "-P", "-F", "#{window_id}"]
    if cwd:
        args.extend(["-c", cwd])
    if name:
        args.extend(["-n", name])
    return _run(args, dest).strip()


def send_text(window_id: str, text: str, dest: str | None = None) -> None:
    """Send literal text to a window's foreground pane. No Enter."""
    if not text:
        return
    _run(["send-keys", "-t", window_id, "-l", text], dest)


def enter_copy_mode_up(session: str) -> bool:
    """Enter copy-mode in the session's active pane and scroll up one page.

    Returns True if copy-mode was triggered. Returns False (and does
    nothing) when the active pane is on the alternate screen — i.e. a
    full-screen TUI app like vim/htop/claude is running. Those apps
    own PgUp themselves; intervening leaves the cursor mis-positioned
    after copy-mode exits.

    Enters with -e so that scrolling back down to the live screen
    leaves copy-mode on its own. Without it tmux parks at the bottom
    of the history and the pane stays inert until something dismisses
    it -- Escape, or a click on window managers where clicks reach
    tmux at all. -e makes the wheel round-trip symmetric.
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
    _run(["copy-mode", "-e", "-u", "-t", session])
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


def set_status_bar(session: str, on: bool, dest: str | None = None) -> None:
    _run(
        ["set-option", "-t", session, "status", "on" if on else "off"],
        dest,
    )


def rename_window(window_id: str, name: str, dest: str | None = None) -> None:
    _run(["rename-window", "-t", window_id, name], dest)


def kill_window(window_id: str, dest: str | None = None) -> None:
    _run(["kill-window", "-t", window_id], dest)


def select_window(window_id: str, dest: str | None = None) -> None:
    _run(["select-window", "-t", window_id], dest)


def swap_windows(a: str, b: str, dest: str | None = None) -> None:
    _run(["swap-window", "-s", a, "-t", b], dest)


def list_windows_with_previews(session: str, preview_lines: int) -> list[WindowInfo]:
    """Naive fetch: one tmux call per window plus one to list them.

    Kept as the reference implementation that fetch_batch is pinned
    against; fetch_batch is what actually runs, because this shape costs
    a full round trip per window once a box is reached over ssh.
    """
    windows = list_windows(session)
    return [
        replace(w, preview=capture_preview(w.id, preview_lines)) for w in windows
    ]


# One round trip has to carry everything a poll needs: the window list,
# each pane's foreground argv (which means reading /proc on the box that
# owns the process, not ours), and every preview. Markers are prefixed
# with a per-call nonce so that pane content -- which is arbitrary text
# and could contain anything we might otherwise use as a delimiter --
# cannot be mistaken for protocol.
_BATCH_SCRIPT = r"""
set -u
lines=%(lines)s
nonce=%(nonce)s

fg_cmd() {
  p=$1
  [ -r "/proc/$p/stat" ] || return 0
  s=$(cat "/proc/$p/stat" 2>/dev/null) || return 0
  rest=${s##*\)}
  # After the comm field: state ppid pgrp session tty_nr tpgid
  set -- $rest
  [ $# -ge 6 ] || return 0
  t=$6
  case "$t" in ''|*[!0-9-]*) return 0 ;; esac
  [ "$t" -gt 0 ] || return 0
  [ "$t" = "$p" ] && return 0
  [ -r "/proc/$t/cmdline" ] || return 0
  tr '\0' ' ' < "/proc/$t/cmdline" 2>/dev/null
}

rows=$(tmux list-windows -a -F \
  "$nonce W #{window_id}	#{window_index}	#{window_name}	#{window_active}	#{pane_current_command}	#{pane_current_path}	#{pane_pid}	#{session_name}") || exit $?
printf '%%s\n' "$rows"

printf '%%s\n' "$rows" | while IFS='	' read -r head idx name active cur path pid sess; do
  wid=${head##* }
  printf '%%s C %%s %%s\n' "$nonce" "$wid" "$(fg_cmd "$pid")"
  printf '%%s P %%s\n' "$nonce" "$wid"
  tmux capture-pane -p -J -t "$wid" -S "-$lines" 2>/dev/null
done
printf '%%s END\n' "$nonce"
"""


def fetch_box(dest: str | None, preview_lines: int) -> list[WindowInfo]:
    """Every window of every session on one box, in a single round trip.

    A box with no tmux server running is not an error -- it is a box
    with no sessions, which is exactly what an idle machine looks like.
    """
    nonce = "R" + secrets.token_hex(8)
    script = _BATCH_SCRIPT % {
        "lines": shlex.quote(str(preview_lines)),
        "nonce": shlex.quote(nonce),
    }
    rc, out, err = ssh.run(dest, ["sh", "-s"], stdin=script)
    if rc != 0:
        if _no_server(err):
            return []
        raise TmuxError(["list-windows", "-a"], rc, err)
    return _parse_batch(out, nonce, dest)


def _no_server(stderr: str) -> bool:
    lowered = stderr.lower()
    return "no server running" in lowered or "error connecting to" in lowered


def _parse_batch(out: str, nonce: str, dest: str | None = None) -> list[WindowInfo]:
    order: list[str] = []
    fields: dict[str, list[str]] = {}
    commands: dict[str, str] = {}
    previews: dict[str, list[str]] = {}
    current: str | None = None

    for line in out.split("\n"):
        if line.startswith(nonce + " "):
            body = line[len(nonce) + 1 :]
            kind, _, rest = body.partition(" ")
            if kind == "W":
                parts = rest.split("\t")
                if len(parts) >= 8:
                    wid = parts[0]
                    order.append(wid)
                    fields[wid] = parts
                current = None
            elif kind == "C":
                wid, _, cmd = rest.partition(" ")
                commands[wid] = cmd.strip()
                current = None
            elif kind == "P":
                current = rest.strip()
                previews[current] = []
            else:  # END
                current = None
            continue
        if current is not None:
            previews[current].append(line)

    windows: list[WindowInfo] = []
    for wid in order:
        parts = fields[wid]
        try:
            pane_pid = int(parts[6])
        except ValueError:
            pane_pid = 0
        preview = "\n".join(previews.get(wid, [])).rstrip("\n")
        windows.append(
            WindowInfo(
                id=wid,
                index=int(parts[1]),
                name=parts[2],
                active=(parts[3] == "1"),
                current_command=parts[4],
                current_path=parts[5],
                last_command=commands.get(wid, ""),
                pane_pid=pane_pid,
                preview=preview,
                dest=dest,
                session=parts[7],
            )
        )
    return windows
