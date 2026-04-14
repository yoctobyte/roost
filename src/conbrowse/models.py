from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindowInfo:
    id: str
    index: int
    name: str
    active: bool
    preview: str = ""


@dataclass(frozen=True)
class AppState:
    windows: tuple[WindowInfo, ...] = field(default_factory=tuple)
    selected_id: str | None = None

    def by_id(self, window_id: str) -> WindowInfo | None:
        for w in self.windows:
            if w.id == window_id:
                return w
        return None
