import subprocess
from dataclasses import replace

from conbrowse.models import WindowInfo


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


def ensure_session(name: str) -> None:
    if session_exists(name):
        return
    _run(["new-session", "-d", "-s", name])


def kill_session(name: str) -> None:
    if session_exists(name):
        _run(["kill-session", "-t", f"={name}"])


_LIST_FMT = (
    "#{window_id}\t#{window_index}\t#{window_name}\t#{window_active}\t"
    "#{pane_current_command}\t#{pane_current_path}"
)


def list_windows(session: str) -> list[WindowInfo]:
    out = _run(["list-windows", "-t", f"={session}", "-F", _LIST_FMT])
    result: list[WindowInfo] = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        wid, idx, name, active, cmd, path = parts[:6]
        result.append(
            WindowInfo(
                id=wid,
                index=int(idx),
                name=name,
                active=(active == "1"),
                current_command=cmd,
                current_path=path,
            )
        )
    return result


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


def new_window(session: str, name: str | None = None) -> str:
    args = ["new-window", "-d", "-t", f"={session}", "-P", "-F", "#{window_id}"]
    if name:
        args.extend(["-n", name])
    return _run(args).strip()


def rename_window(window_id: str, name: str) -> None:
    _run(["rename-window", "-t", window_id, name])


def kill_window(window_id: str) -> None:
    _run(["kill-window", "-t", window_id])


def select_window(window_id: str) -> None:
    _run(["select-window", "-t", window_id])


def list_windows_with_previews(session: str, preview_lines: int) -> list[WindowInfo]:
    windows = list_windows(session)
    return [
        replace(w, preview=capture_preview(w.id, preview_lines)) for w in windows
    ]
