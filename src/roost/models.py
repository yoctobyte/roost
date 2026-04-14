from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindowInfo:
    id: str
    index: int
    name: str
    active: bool
    preview: str = ""
    current_command: str = ""
    current_path: str = ""
    # Full argv of the foreground process running under the pane, if any.
    # Empty when the pane is idle at a shell prompt. Captured from
    # /proc/<tpgid>/cmdline via the pane's shell pid.
    last_command: str = ""
    pane_pid: int = 0


@dataclass(frozen=True)
class AppState:
    windows: tuple[WindowInfo, ...] = field(default_factory=tuple)
    selected_id: str | None = None

    def by_id(self, window_id: str) -> WindowInfo | None:
        for w in self.windows:
            if w.id == window_id:
                return w
        return None
