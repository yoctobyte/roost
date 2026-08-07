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

# Targets are aimed well above the "barely legible" line -- readable but
# dim (grey on black) is still a bad monitoring experience. Bright
# colors aim higher than their normal counterparts so the two stay
# distinguishable, since more contrast is what "bright" means anyway.
NORMAL_MIN_RATIO = 6.0
BRIGHT_MIN_RATIO = 9.0
EXTENDED_MIN_RATIO = 4.5

# Contrast can always be won by going to pure white or black, which
# throws the hue away. Cap how far lightness may travel so a blue stays
# blue; colors that cannot reach their target within the cap settle for
# the cap.
MAX_LIGHTNESS = 0.88
MIN_LIGHTNESS = 0.22

# Floor a normal color may be pushed back down to when it needs to make
# room for its bright counterpart, and the lightness gap that counts as
# "distinguishable".
SEPARATION_FLOOR_RATIO = 4.5
MIN_SEPARATION = 0.10

# Green, yellow and cyan are intrinsically light: on a light background
# they must go dark to be legible, which leaves no lightness headroom to
# separate the pair. Muting the normal one instead keeps the two
# distinguishable by vividness.
SEPARATION_SATURATION = 0.45

# Slack in the "already distinct enough" checks, so a pair sitting right
# on MIN_SEPARATION is left alone instead of being nudged by a rounding
# error's worth of lightness.
SEPARATION_EPSILON = 0.005


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


def _scale_saturation(color: str, factor: float) -> str:
    h, lightness, s = colorsys.rgb_to_hls(*_parse(color))
    return _format(colorsys.hls_to_rgb(h, lightness, s * factor))


def _lightness(color: str) -> float:
    return colorsys.rgb_to_hls(*_parse(color))[1]


def _lightens_against(bg: str) -> bool:
    """True when readable text on `bg` is lighter than the background."""
    return _luminance(_parse(bg)) < 0.5


def fix_color(color: str, bg: str, min_ratio: float) -> str:
    """Nudge `color`'s lightness away from `bg` until it clears `min_ratio`.

    Returns `color` unchanged when it already passes. When the target is
    unreachable within the lightness cap, returns the capped color.
    """
    if contrast_ratio(color, bg) >= min_ratio:
        return color
    rgb = _parse(color)
    lightness = _lightness(color)
    lighten = _lightens_against(bg)
    limit = MAX_LIGHTNESS if lighten else MIN_LIGHTNESS
    # Already past the cap and still short of the target: nothing on
    # offer that would not destroy the hue.
    if (lightness >= limit) if lighten else (lightness <= limit):
        return color
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


def separate(normal: str, bright: str, bg: str) -> str:
    """Pull `normal` back toward `bg` so it stays distinct from `bright`.

    On a light background both members of a pair are darkened, and the
    lightness cap can land them on the same color. The normal one is the
    less prominent of the two, so it gives way -- but never past
    SEPARATION_FLOOR_RATIO, and never at all if it has no room to spare.
    """
    if contrast_ratio(normal, bg) < SEPARATION_FLOOR_RATIO:
        return normal
    lighten = _lightens_against(bg)
    l_normal, l_bright = _lightness(normal), _lightness(bright)
    want = l_bright - MIN_SEPARATION if lighten else l_bright + MIN_SEPARATION
    want = max(0.0, min(1.0, want))
    if (
        (l_normal <= want + SEPARATION_EPSILON)
        if lighten
        else (l_normal >= want - SEPARATION_EPSILON)
    ):
        return normal  # already distinct enough
    rgb = _parse(normal)
    if contrast_ratio(_format(_with_lightness(rgb, want)), bg) >= SEPARATION_FLOOR_RATIO:
        return _format(_with_lightness(rgb, want))
    # Cannot separate fully; give back as much as the floor allows. The
    # passing side of the range is the one we started from, so this is
    # the same bisection as fix_color, bounded by `want` instead.
    lo, hi = (want, l_normal) if lighten else (l_normal, want)
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if contrast_ratio(_format(_with_lightness(rgb, mid)), bg) >= SEPARATION_FLOOR_RATIO:
            if lighten:
                hi = mid
            else:
                lo = mid
        elif lighten:
            lo = mid
        else:
            hi = mid
    settled = _format(_with_lightness(rgb, hi if lighten else lo))
    if abs(_lightness(settled) - l_bright) >= MIN_SEPARATION:
        return settled
    # Out of lightness headroom -- mute the normal one instead, then
    # restore its contrast floor if desaturating cost it any.
    return fix_color(
        _scale_saturation(settled, SEPARATION_SATURATION),
        bg,
        SEPARATION_FLOOR_RATIO,
    )


def push_apart(bright: str, normal: str, bg: str) -> str:
    """Move `bright` further from `bg` when `normal` cannot give way.

    Moving away from the background only ever gains contrast, so this
    needs no floor -- just the lightness cap that keeps the hue.
    """
    lighten = _lightens_against(bg)
    l_bright, l_normal = _lightness(bright), _lightness(normal)
    if lighten:
        want = min(l_normal + MIN_SEPARATION, MAX_LIGHTNESS)
    else:
        want = max(l_normal - MIN_SEPARATION, MIN_LIGHTNESS)
    if (
        (l_bright >= want - SEPARATION_EPSILON)
        if lighten
        else (l_bright <= want + SEPARATION_EPSILON)
    ):
        return bright  # already distinct enough
    return _format(_with_lightness(_parse(bright), want))


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


def _system_target(index: int) -> float:
    return NORMAL_MIN_RATIO if index < 8 else BRIGHT_MIN_RATIO


@lru_cache(maxsize=8)
def fixed_palette(bg: str) -> tuple[str, ...]:
    """256-entry palette with every entry readable against `bg`."""
    base = base_palette()
    out = [
        fix_color(c, bg, _system_target(i) if i < 16 else EXTENDED_MIN_RATIO)
        for i, c in enumerate(base)
    ]
    for i in range(8):
        # Only a color we already had to correct may give way. One that
        # was fine as-is has nothing to apologise for -- black on a light
        # background is perfect at 18:1, and dropping it to 6:1 just to
        # make room for bright-black would invert the pair and spoil the
        # most important color on the theme.
        if contrast_ratio(base[i], bg) < NORMAL_MIN_RATIO:
            out[i] = separate(out[i], out[i + 8], bg)
        else:
            out[i + 8] = push_apart(out[i + 8], out[i], bg)
    return tuple(out)
