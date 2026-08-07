import json
import os
import zlib
from dataclasses import asdict, dataclass, field, fields

from roost import palette


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
DEFAULT_AUTO_COLOR_TABS = True
DEFAULT_SHOW_STATUS_BAR = False
DEFAULT_SORT_KIND = "folder"
SORT_KINDS = ("folder", "name", "app", "color", "age")
DEFAULT_MOUSE_MODE = "vte"
MOUSE_MODES = ("vte", "tmux")
DEFAULT_FIX_CONTRAST = True


@dataclass
class Settings:
    overview_font_size: int = DEFAULT_OVERVIEW_FONT_SIZE
    theme: str = DEFAULT_THEME
    # Map of cwd prefix -> TAB_COLORS key. Explicit colors are resolved
    # by longest-prefix match against a tab's current working directory,
    # so setting a color on /home/me/projects/foo carries into its
    # subdirectories and any shell that cd's deeper keeps the color.
    cwd_colors: dict = field(default_factory=dict)
    # When true, tabs without an explicit cwd_colors entry get a
    # deterministic color derived from the project root of their cwd.
    auto_color_tabs: bool = DEFAULT_AUTO_COLOR_TABS
    remember_tabs: bool = DEFAULT_REMEMBER_TABS
    show_status_bar: bool = DEFAULT_SHOW_STATUS_BAR
    sort_kind: str = DEFAULT_SORT_KIND
    # "vte": tmux mouse off; VTE owns selection, roost handles wheel.
    # "tmux": tmux mouse on; tmux owns selection (scroll-while-select),
    #         scroll wheel goes to tmux directly. Selection is captured
    #         to a tmux buffer; copy via right-click "Copy".
    mouse_mode: str = DEFAULT_MOUSE_MODE
    # ssh destinations of the other boxes to watch, as typed -- an alias
    # from ~/.ssh/config, or user@host. This machine is always present
    # and is not listed here.
    boxes: list = field(default_factory=list)
    # Remap the terminal's indexed colors so every one of them stays
    # readable against the theme background. Trades ANSI fidelity for
    # legibility -- the point is monitoring processes, not rendering.
    fix_contrast: bool = DEFAULT_FIX_CONTRAST

    def clamp(self) -> "Settings":
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(self.overview_font_size)))
        theme = self.theme if self.theme in THEMES else DEFAULT_THEME
        colors = {
            os.path.normpath(str(k)): str(v)
            for k, v in (self.cwd_colors or {}).items()
            if str(v) in TAB_COLORS and str(k)
        }
        return Settings(
            overview_font_size=size,
            theme=theme,
            cwd_colors=colors,
            auto_color_tabs=bool(self.auto_color_tabs),
            remember_tabs=bool(self.remember_tabs),
            show_status_bar=bool(self.show_status_bar),
            sort_kind=(
                self.sort_kind if self.sort_kind in SORT_KINDS else DEFAULT_SORT_KIND
            ),
            mouse_mode=(
                self.mouse_mode if self.mouse_mode in MOUSE_MODES else DEFAULT_MOUSE_MODE
            ),
            fix_contrast=bool(self.fix_contrast),
            boxes=_clean_boxes(self.boxes),
        )

    def theme_obj(self) -> Theme:
        return THEMES[self.theme if self.theme in THEMES else DEFAULT_THEME]

    def terminal_palette(self) -> tuple[str, ...] | None:
        """Palette to hand VTE, or None to keep its built-in one."""
        if not self.fix_contrast:
            return None
        return palette.fixed_palette(self.theme_obj().bg)

    def resolve_tab_color(self, cwd: str) -> TabColor | None:
        if not cwd:
            return None
        cwd_n = os.path.normpath(cwd)
        best_prefix = ""
        best_key: str | None = None
        for prefix, key in self.cwd_colors.items():
            if cwd_n == prefix or cwd_n.startswith(prefix.rstrip("/") + "/"):
                if len(prefix) > len(best_prefix):
                    best_prefix = prefix
                    best_key = key
        if best_key is not None:
            return TAB_COLORS.get(best_key)
        if self.auto_color_tabs:
            return TAB_COLORS[_auto_color_key(cwd_n)]
        return None

    def explicit_color_for(self, cwd: str) -> tuple[str, str] | None:
        """Return (prefix, color_key) of the longest explicit match."""
        if not cwd:
            return None
        cwd_n = os.path.normpath(cwd)
        best_prefix = ""
        best_key: str | None = None
        for prefix, key in self.cwd_colors.items():
            if cwd_n == prefix or cwd_n.startswith(prefix.rstrip("/") + "/"):
                if len(prefix) > len(best_prefix):
                    best_prefix = prefix
                    best_key = key
        if best_key is None:
            return None
        return best_prefix, best_key

    def set_cwd_color(self, cwd: str, color_key: str | None) -> None:
        if not cwd:
            return
        key_path = os.path.normpath(cwd)
        if color_key is None or color_key not in TAB_COLORS:
            self.cwd_colors.pop(key_path, None)
        else:
            self.cwd_colors[key_path] = color_key


def _clean_boxes(boxes) -> list:
    """Trimmed, de-duplicated destinations, original order preserved."""
    out: list[str] = []
    for raw in boxes or []:
        dest = str(raw).strip()
        if dest and dest not in out:
            out.append(dest)
    return out


_KNOWN_PARENTS = {
    "projects", "project", "src", "source", "code", "work", "workspace",
    "dev", "repos", "repo", "git", "github", "gitlab", "Documents",
    "Downloads", "Code",
}


def project_root(cwd: str) -> str:
    """Best-effort project-root derivation, no filesystem I/O.

    If the first path component is a known container directory
    ("projects", "src", "code", ...) we use two components so that
    sibling projects get distinct roots. Otherwise one component.
    """
    if not cwd:
        return ""
    cwd = os.path.normpath(cwd)
    home = os.path.expanduser("~")
    if cwd == home or cwd == "/":
        return cwd
    if cwd.startswith(home + "/"):
        rest = cwd[len(home) + 1 :]
        parts = rest.split("/")
        if not parts or not parts[0]:
            return home
        first = parts[0]
        if first in _KNOWN_PARENTS and len(parts) >= 2:
            return os.path.join(home, first, parts[1])
        return os.path.join(home, first)
    parts = cwd.strip("/").split("/")
    if not parts:
        return cwd
    if parts[0] in _KNOWN_PARENTS and len(parts) >= 2:
        return "/" + "/".join(parts[:2])
    return "/" + parts[0]


def _auto_color_key(cwd: str) -> str:
    root = project_root(cwd) or cwd
    keys = list(TAB_COLORS.keys())
    h = zlib.crc32(root.encode("utf-8", "replace"))
    return keys[h % len(keys)]


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
