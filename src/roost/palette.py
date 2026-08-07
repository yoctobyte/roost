"""Contrast-corrected terminal palettes.

VTE renders indexed SGR colors from a fixed palette tuned for a black
background. On the brown and light themes that leaves several entries
effectively invisible (ANSI 4 on Ubuntu brown is ~1.2:1; ANSI 15 on
white is ~1.0:1). VTE 0.76 has no minimum-contrast setting and no way
to intervene per cell, but `Vte.Terminal.set_colors` accepts a full
256-entry palette -- so we precompute one whose every entry clears a
contrast threshold against the theme background.

Corrections keep hue and saturation and move only lightness, by the
smallest amount that clears the threshold, so colored output still
reads as "the blue one" / "the yellow one".
"""

import colorsys
from functools import lru_cache

# Standard xterm system colors (indices 0-15).
_SYSTEM = (
    "#000000", "#cd0000", "#00cd00", "#cdcd00",
    "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
    "#7f7f7f", "#ff0000", "#00ff00", "#ffff00",
    "#5c5cff", "#ff00ff", "#00ffff", "#ffffff",
)

_CUBE_STEPS = (0, 95, 135, 175, 215, 255)

# The 16 system colors carry text; the cube and greyscale ramp are more
# often decoration, so they get a laxer target to stay recognisable.
SYSTEM_MIN_RATIO = 4.0
EXTENDED_MIN_RATIO = 2.5


def _parse(hex_color: str) -> tuple[float, float, float]:
    s = hex_color.lstrip("#")
    return tuple(int(s[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _format(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance."""
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(_parse(a)), _luminance(_parse(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _with_lightness(rgb: tuple[float, float, float], lightness: float) -> tuple[float, float, float]:
    h, _, s = colorsys.rgb_to_hls(*rgb)
    return colorsys.hls_to_rgb(h, lightness, s)


def fix_color(color: str, bg: str, min_ratio: float) -> str:
    """Nudge `color`'s lightness away from `bg` until it clears `min_ratio`.

    Returns `color` unchanged when it already passes. When the target is
    unreachable even at full white/black, returns the closest attempt.
    """
    if contrast_ratio(color, bg) >= min_ratio:
        return color
    rgb = _parse(color)
    _, lightness, _ = colorsys.rgb_to_hls(*rgb)
    lighten = _luminance(_parse(bg)) < 0.5
    limit = 1.0 if lighten else 0.0
    if contrast_ratio(_format(_with_lightness(rgb, limit)), bg) < min_ratio:
        return _format(_with_lightness(rgb, limit))
    # Contrast is monotone in lightness once we commit to a direction,
    # so bisect for the smallest change that clears the threshold.
    lo, hi = (lightness, limit) if lighten else (limit, lightness)
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if contrast_ratio(_format(_with_lightness(rgb, mid)), bg) >= min_ratio:
            if lighten:
                hi = mid
            else:
                lo = mid
        elif lighten:
            lo = mid
        else:
            hi = mid
    return _format(_with_lightness(rgb, hi if lighten else lo))


def base_palette() -> list[str]:
    """The uncorrected xterm 256-color palette."""
    out = list(_SYSTEM)
    for r in _CUBE_STEPS:
        for g in _CUBE_STEPS:
            for b in _CUBE_STEPS:
                out.append(f"#{r:02x}{g:02x}{b:02x}")
    for i in range(24):
        v = 8 + i * 10
        out.append(f"#{v:02x}{v:02x}{v:02x}")
    return out


@lru_cache(maxsize=8)
def fixed_palette(bg: str) -> tuple[str, ...]:
    """256-entry palette with every entry readable against `bg`."""
    base = base_palette()
    return tuple(
        fix_color(c, bg, SYSTEM_MIN_RATIO if i < 16 else EXTENDED_MIN_RATIO)
        for i, c in enumerate(base)
    )
