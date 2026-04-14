import json
import os
from dataclasses import asdict, dataclass, fields


@dataclass
class Theme:
    key: str
    name: str
    fg: str
    bg: str


THEMES: dict[str, Theme] = {
    "ubuntu": Theme("ubuntu", "Ubuntu Brown", "#ffffff", "#300a24"),
    "black": Theme("black", "Black", "#c5c8c6", "#000000"),
    "white": Theme("white", "White", "#1a1a1a", "#ffffff"),
    "soft-white": Theme("soft-white", "Soft White", "#2a2a2a", "#f5f1e8"),
}

DEFAULT_THEME = "ubuntu"
DEFAULT_OVERVIEW_FONT_SIZE = 4
MIN_FONT_SIZE = 2
MAX_FONT_SIZE = 14


@dataclass
class Settings:
    overview_font_size: int = DEFAULT_OVERVIEW_FONT_SIZE
    theme: str = DEFAULT_THEME

    def clamp(self) -> "Settings":
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(self.overview_font_size)))
        theme = self.theme if self.theme in THEMES else DEFAULT_THEME
        return Settings(overview_font_size=size, theme=theme)

    def theme_obj(self) -> Theme:
        return THEMES[self.theme if self.theme in THEMES else DEFAULT_THEME]


def settings_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "roost", "settings.json")


def load() -> Settings:
    path = settings_path()
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    allowed = {f.name for f in fields(Settings)}
    filtered = {k: v for k, v in data.items() if k in allowed}
    try:
        return Settings(**filtered).clamp()
    except TypeError:
        return Settings()


def save(settings: Settings) -> None:
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(asdict(settings.clamp()), fh, indent=2)
