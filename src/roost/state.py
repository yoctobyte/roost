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

SCHEMA_VERSION = 1


@dataclass
class SavedWindow:
    index: int
    name: str
    cwd: str = ""
    last_command: str = ""
    current_command: str = ""


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


def build_snapshot(session: str, windows: Sequence[WindowInfo]) -> Snapshot:
    return Snapshot(
        saved_at=time.time(),
        session=session,
        windows=[
            SavedWindow(
                index=w.index,
                name=w.name,
                cwd=w.current_path,
                last_command=w.last_command,
                current_command=w.current_command,
            )
            for w in windows
        ],
    )


def change_key(windows: Sequence[SavedWindow]) -> tuple:
    """Stable key for change-detection — excludes the timestamp."""
    return tuple(
        (w.index, w.name, w.cwd, w.last_command, w.current_command)
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
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
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
