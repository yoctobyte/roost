from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindowInfo:
    # tmux's own window id, unique only within one server. Two boxes, or
    # even one box's two sessions, can both hold an "@1" -- so this is
    # never the identity roost uses. See `key`.
    id: str
    index: int
    name: str
    active: bool
    preview: str = ""
    current_command: str = ""
    current_path: str = ""
    # ssh destination of the box this window lives on, None for this
    # machine, and the tmux session that holds it.
    dest: str | None = None
    session: str = ""
    # Full argv of the foreground process running under the pane, if any.
    # Empty when the pane is idle at a shell prompt. Captured from
    # /proc/<tpgid>/cmdline via the pane's shell pid.
    last_command: str = ""
    pane_pid: int = 0

    @property
    def key(self) -> str:
        """Identity across every box and session roost is watching.

        The unit separator cannot occur in a destination, session name
        or window id, so the parts can never run together ambiguously.
        """
        return f"{self.dest or ''}\x1f{self.session}\x1f{self.id}"

    @property
    def box_label(self) -> str:
        return self.dest or "this machine"


@dataclass(frozen=True)
class AppState:
    windows: tuple[WindowInfo, ...] = field(default_factory=tuple)
    selected_id: str | None = None

    def by_key(self, key: str) -> WindowInfo | None:
        for w in self.windows:
            if w.key == key:
                return w
        return None

    def sources(self) -> list[tuple[str | None, str]]:
        """Distinct (destination, session) pairs currently present."""
        seen: list[tuple[str | None, str]] = []
        for w in self.windows:
            pair = (w.dest, w.session)
            if pair not in seen:
                seen.append(pair)
        return seen
