"""Turn a window running Claude Code into a command that resumes it.

A plain `claude` restored after a reboot starts a *new* conversation.
Claude Code keeps a registry of its live processes in
~/.claude/sessions/<pid>.json -- session id, cwd, and the tmux pane it
runs in ("roost:@2.%2"). Joining that with the snapshot lets restore
put `claude ... --resume <session id>` on the prompt instead.

Local machine only: remote boxes keep their own registry.
"""

import glob
import json
import os
import shlex

# Flags that pick which conversation to open. Dropped from the saved
# argv because the restore command names the session explicitly.
_RESUME_WITH_ARG = ("--resume", "-r", "--session-id")
_RESUME_BARE = ("--continue", "-c")


def _registry_dir() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "sessions")


def _argv(pid: int) -> list[str] | None:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    parts = [p.decode(errors="replace") for p in raw.split(b"\0") if p]
    return parts or None


def live_sessions() -> dict[tuple[str, str], tuple[str, str, list[str]]]:
    """(tmux session, window id) -> (session id, cwd, argv) for live claudes.

    Stale registry files (process gone, or pid reused by something that
    is not claude) are skipped.
    """
    found: dict[tuple[str, str], tuple[str, str, list[str]]] = {}
    for path in glob.glob(os.path.join(_registry_dir(), "*.json")):
        try:
            with open(path) as fh:
                d = json.load(fh)
            pid = int(d["pid"])
            sid = str(d["sessionId"])
            target = str(d.get("tmux") or "")
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if ":" not in target or not sid:
            continue
        argv = _argv(pid)
        if not argv or "claude" not in os.path.basename(argv[0]):
            continue
        session, _, rest = target.partition(":")
        window_id = rest.split(".", 1)[0]
        found[(session, window_id)] = (sid, str(d.get("cwd") or ""), argv)
    return found


def resume_command(argv: list[str], session_id: str) -> str:
    """`argv` with any resume/continue choice replaced by `--resume <id>`."""
    kept: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg in _RESUME_WITH_ARG:
            skip = True
            continue
        if arg in _RESUME_BARE or arg.startswith(
            tuple(f + "=" for f in _RESUME_WITH_ARG)
        ):
            continue
        kept.append(arg)
    kept[0] = os.path.basename(kept[0])
    return shlex.join(kept + ["--resume", session_id])
