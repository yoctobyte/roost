"""Remember the Claude Code sessions on this machine, and how to resume them.

A plain `claude` restored after a reboot starts a *new* conversation.
Claude Code keeps a registry of its live processes in
~/.claude/sessions/<pid>.json -- session id, cwd, name, status, and the
tmux pane it runs in ("roost:@2.%2"). From that, roost:

- puts `claude ... --resume <session id>` into the reboot snapshot, and
- keeps a history of every session it has seen (live or ended), so the
  Status tab can bring one back with a click.

Local machine only: remote boxes keep their own registry.
"""

import glob
import json
import os
import shlex
import time
from dataclasses import asdict, dataclass

# Flags that pick which conversation to open. Dropped from the saved
# argv because the restore command names the session explicitly.
_RESUME_WITH_ARG = ("--resume", "-r", "--session-id")
_RESUME_BARE = ("--continue", "-c")


@dataclass
class LiveSession:
    session_id: str
    pid: int
    cwd: str
    name: str
    status: str  # "idle", "busy", ... as Claude Code reports it
    tmux: str  # "session:@window.%pane", or "" outside tmux
    argv: list[str]

    @property
    def tmux_window(self) -> tuple[str, str] | None:
        """(tmux session, window id), or None when not in tmux."""
        if ":" not in self.tmux:
            return None
        session, _, rest = self.tmux.partition(":")
        return session, rest.split(".", 1)[0]


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


def registry_entries() -> list[LiveSession]:
    """Every live interactive claude on this machine, in tmux or not.

    Stale registry files (process gone, or pid reused by something that
    is not claude) are skipped.
    """
    found: list[LiveSession] = []
    for path in glob.glob(os.path.join(_registry_dir(), "*.json")):
        try:
            with open(path) as fh:
                d = json.load(fh)
            pid = int(d["pid"])
            sid = str(d["sessionId"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not sid or d.get("kind", "interactive") != "interactive":
            continue
        argv = _argv(pid)
        if not argv or "claude" not in os.path.basename(argv[0]):
            continue
        found.append(
            LiveSession(
                session_id=sid,
                pid=pid,
                cwd=str(d.get("cwd") or ""),
                name=str(d.get("name") or ""),
                status=str(d.get("status") or ""),
                tmux=str(d.get("tmux") or ""),
                argv=argv,
            )
        )
    return found


def live_sessions() -> dict[tuple[str, str], tuple[str, str, list[str]]]:
    """(tmux session, window id) -> (session id, cwd, argv) for live claudes."""
    found = {}
    for s in registry_entries():
        where = s.tmux_window
        if where is not None:
            found[where] = (s.session_id, s.cwd, s.argv)
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


# -- history -------------------------------------------------------------


@dataclass
class SessionRecord:
    session_id: str
    name: str = ""
    cwd: str = ""
    command: str = ""  # ready-to-run resume command
    tmux: str = ""  # where it last ran ("" = outside tmux)
    first_seen: float = 0.0
    last_seen: float = 0.0  # while live: when it was last seen changing
    ended: bool = False


def history_path() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state"
    )
    return os.path.join(base, "roost", "claude_sessions.json")


class SessionHistory:
    """Every Claude session seen on this machine, persisted across restarts.

    The file is written only when something a reader cares about changes
    (a session appears, ends, is renamed or moves), not on every poll.
    """

    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.live: dict[str, LiveSession] = {}
        self._load()
        # Whatever was live when roost last ran has not been seen since;
        # the first update() marks the ones still running as live again.
        self._first_update = True

    def _load(self) -> None:
        try:
            with open(history_path()) as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        for raw in data.get("sessions", []) if isinstance(data, dict) else []:
            try:
                rec = SessionRecord(**raw)
            except TypeError:
                continue
            self.records[rec.session_id] = rec

    def _save(self) -> None:
        path = history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(
                {"version": 1, "sessions": [asdict(r) for r in self.sorted()]},
                fh,
                indent=2,
            )
        os.replace(tmp, path)

    def update(self, entries: list[LiveSession], now: float | None = None) -> bool:
        """Fold one registry scan in. Returns True if anything changed."""
        now = time.time() if now is None else now
        starting = self._first_update
        changed = starting
        self._first_update = False
        self.live = {e.session_id: e for e in entries}
        for e in entries:
            rec = self.records.get(e.session_id)
            if rec is None:
                rec = self.records[e.session_id] = SessionRecord(
                    session_id=e.session_id, first_seen=now
                )
            fresh = (
                e.name,
                e.cwd,
                resume_command(e.argv, e.session_id),
                e.tmux,
                False,
            )
            if (
                rec.name, rec.cwd, rec.command, rec.tmux, rec.ended
            ) != fresh or not rec.last_seen:
                rec.name, rec.cwd, rec.command, rec.tmux, rec.ended = fresh
                rec.last_seen = now
                changed = True
        for rec in self.records.values():
            if not rec.ended and rec.session_id not in self.live:
                rec.ended = True
                # Ended while roost was not running: the last sighting
                # is the best time we have, so keep it.
                if not starting:
                    rec.last_seen = now
                changed = True
        if changed:
            try:
                self._save()
            except OSError:
                pass
        return changed

    def forget(self, session_id: str) -> None:
        if self.records.pop(session_id, None) is not None:
            try:
                self._save()
            except OSError:
                pass

    def sorted(self) -> list[SessionRecord]:
        """Live first, then most recently seen."""
        return sorted(
            self.records.values(), key=lambda r: (r.ended, -r.last_seen)
        )
