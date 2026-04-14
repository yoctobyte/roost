import json
import os
from dataclasses import asdict, dataclass, field, fields


@dataclass
class Theme:
    key: str
    name: str
    fg: str
    bg: str


@dataclass
class TabColor:
    key: str
    name: str
    bg: str
    fg: str = "#222222"


TAB_COLORS: dict[str, TabColor] = {
    "peach":  TabColor("peach",  "Peach",  "#ffd1b3"),
    "rose":   TabColor("rose",   "Rose",   "#ffc1cc"),
    "lemon":  TabColor("lemon",  "Lemon",  "#fff3a3"),
    "mint":   TabColor("mint",   "Mint",   "#b8e6c1"),
    "sky":    TabColor("sky",    "Sky",    "#b3dcff"),
    "lilac":  TabColor("lilac",  "Lilac",  "#d8c1f0"),
    "sand":   TabColor("sand",   "Sand",   "#e6d5b8"),
    "grey":   TabColor("grey",   "Grey",   "#d0d0d0"),
}


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
DEFAULT_REMEMBER_TABS = True


@dataclass
class Settings:
    overview_font_size: int = DEFAULT_OVERVIEW_FONT_SIZE
    theme: str = DEFAULT_THEME
    # Map of window name -> TAB_COLORS key. Keyed by name (not tmux
    # window-id) so colors survive session recreation; collisions on
    # rename are accepted as a feature.
    tab_colors: dict = field(default_factory=dict)
    remember_tabs: bool = DEFAULT_REMEMBER_TABS

    def clamp(self) -> "Settings":
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(self.overview_font_size)))
        theme = self.theme if self.theme in THEMES else DEFAULT_THEME
        colors = {
            str(k): str(v)
            for k, v in (self.tab_colors or {}).items()
            if str(v) in TAB_COLORS
        }
        return Settings(
            overview_font_size=size,
            theme=theme,
            tab_colors=colors,
            remember_tabs=bool(self.remember_tabs),
        )

    def theme_obj(self) -> Theme:
        return THEMES[self.theme if self.theme in THEMES else DEFAULT_THEME]

    def tab_color(self, window_name: str) -> TabColor | None:
        key = self.tab_colors.get(window_name)
        if key is None:
            return None
        return TAB_COLORS.get(key)

    def set_tab_color(self, window_name: str, color_key: str | None) -> None:
        if color_key is None or color_key not in TAB_COLORS:
            self.tab_colors.pop(window_name, None)
        else:
            self.tab_colors[window_name] = color_key


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
