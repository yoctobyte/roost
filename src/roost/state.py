"""Persistent snapshot of the managed tmux session.

Writes a small JSON file so roost can offer to recreate windows after a
reboot or crash. Commands are never auto-executed — the file only
records enough to bring the user back to roughly where they were
(window name, working directory, and the command that was running).
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Sequence

from roost.models import WindowInfo

SCHEMA_VERSION = 2
_READABLE_VERSIONS = (1, 2)


@dataclass
class SavedWindow:
    index: int
    name: str
    # Where the pane sat when the snapshot was taken.
    cwd: str = ""
    # The most recent command seen running in this window, which is not
    # necessarily one that was still running at snapshot time -- a window
    # idle at a prompt has no foreground process, but what it last ran is
    # exactly what the user wants back after a crash.
    last_command: str = ""
    # The directory `last_command` was launched from. The shell may have
    # cd'd since, so restoring into `cwd` can be the wrong place.
    last_command_cwd: str = ""
    # Live foreground process name at snapshot time ("bash" when idle).
    current_command: str = ""

    def restore_cwd(self) -> str:
        return self.last_command_cwd or self.cwd


@dataclass
class Snapshot:
    saved_at: float = 0.0
    session: str = ""
    windows: list[SavedWindow] = field(default_factory=list)
    version: int = SCHEMA_VERSION


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state"
    )
    return os.path.join(base, "roost")


def snapshot_path() -> str:
    return os.path.join(state_dir(), "last_session.json")


def build_snapshot(
    session: str,
    windows: Sequence[WindowInfo],
    remembered: dict[str, tuple[str, str]] | None = None,
) -> Snapshot:
    """Snapshot `windows`, preferring remembered commands over live ones.

    `remembered` maps window id -> (command, cwd it was launched from),
    carried across polls by the controller so a window idle at a prompt
    still records what it last ran.
    """
    remembered = remembered or {}
    saved = []
    for w in windows:
        command, command_cwd = remembered.get(w.id, ("", ""))
        saved.append(
            SavedWindow(
                index=w.index,
                name=w.name,
                cwd=w.current_path,
                last_command=command or w.last_command,
                last_command_cwd=command_cwd,
                current_command=w.current_command,
            )
        )
    return Snapshot(saved_at=time.time(), session=session, windows=saved)


def change_key(windows: Sequence[SavedWindow]) -> tuple:
    """Stable key for change-detection — excludes the timestamp."""
    return tuple(
        (
            w.index,
            w.name,
            w.cwd,
            w.last_command,
            w.last_command_cwd,
            w.current_command,
        )
        for w in windows
    )


def save(snap: Snapshot) -> None:
    path = snapshot_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "version": snap.version,
        "saved_at": snap.saved_at,
        "session": snap.session,
        "windows": [
            {
                "index": w.index,
                "name": w.name,
                "cwd": w.cwd,
                "last_command": w.last_command,
                "last_command_cwd": w.last_command_cwd,
                "current_command": w.current_command,
            }
            for w in snap.windows
        ],
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def load() -> Snapshot | None:
    try:
        with open(snapshot_path()) as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("version") not in _READABLE_VERSIONS:
        return None
    wins: list[SavedWindow] = []
    for raw in data.get("windows", []) or []:
        if not isinstance(raw, dict):
            continue
        wins.append(
            SavedWindow(
                index=int(raw.get("index", 0) or 0),
                name=str(raw.get("name", "") or ""),
                cwd=str(raw.get("cwd", "") or ""),
                last_command=str(raw.get("last_command", "") or ""),
                last_command_cwd=str(raw.get("last_command_cwd", "") or ""),
                current_command=str(raw.get("current_command", "") or ""),
            )
        )
    return Snapshot(
        version=SCHEMA_VERSION,
        saved_at=float(data.get("saved_at", 0.0) or 0.0),
        session=str(data.get("session", "") or ""),
        windows=wins,
    )


def clear() -> None:
    try:
        os.remove(snapshot_path())
    except FileNotFoundError:
        pass
