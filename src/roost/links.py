"""Find the URL under a click in a terminal pane.

tmux does not hand us links. In a full-width pane it prints a long URL
in one go and lets the terminal wrap it, so VTE sees a single soft
line and its own matcher copes. In a split pane tmux wraps by itself:
it emits each screen row followed by a hard CRLF, padded to the pane
edge. VTE then sees a hard line break in the middle of the URL -- and
the VTE row spans *both* panes, so joining VTE rows would splice in
whatever the neighbouring pane happens to show.

So we work in tmux's coordinates instead, on rows captured from one
pane. A row that tmux wrapped is exactly pane_width wide; a row that
ended naturally is shorter, because capture-pane trims trailing
blanks. That single fact lets us rebuild the logical line and map a
click position into it.
"""

import re

# Deliberately narrow. These are the schemes we are willing to hand to
# the desktop's URL handler; anything else (javascript:, and whatever a
# hostile program might print) must not become a clickable action.
OPENABLE_SCHEMES = ("http", "https", "ftp", "ftps", "file", "mailto")

# The body stops at whitespace and at the characters that conventionally
# delimit a URL in prose or shell quoting. Parentheses are *allowed*
# through -- plenty of real URLs contain them -- and balanced later.
_URL_RE = re.compile(
    r"(?:(?:https?|ftps?|file)://|mailto:|www\.)"
    r"[^\s<>\"'`\\^\[\]{}|]+",
    re.IGNORECASE,
)

# The same shape as _URL_RE, as a plain string for VTE's PCRE2 matcher.
# Kept next to the regex above so the two cannot drift apart.
VTE_PATTERN = (
    r"(?:(?:https?|ftps?|file)://|mailto:|www\.)"
    r"[^\s<>\"'`\\^\[\]{}|]+"
)

# PCRE2 compile flags, as VTE wants them passed to Vte.Regex.new_for_match.
# VTE refuses a match regex that was not compiled multiline.
PCRE2_CASELESS = 0x00000008
PCRE2_MULTILINE = 0x00000400

# Sentence punctuation that is far more likely to belong to the prose
# around a URL than to the URL itself.
_TRAILING = ".,;:!?"


def _trim(url: str) -> str:
    """Drop trailing punctuation that belongs to the sentence, not the URL."""
    while url:
        if url[-1] in _TRAILING:
            url = url[:-1]
            continue
        # A closing paren only counts if something opened it. "(see
        # http://x/a)" ends the URL at "a"; "http://x/a_(b)" keeps it.
        if url[-1] == ")" and url.count("(") < url.count(")"):
            url = url[:-1]
            continue
        break
    return url


def normalize(url: str) -> str:
    """Give a bare www.host URL the scheme the desktop handler needs."""
    if url.lower().startswith("www."):
        return "https://" + url
    return url


def is_openable(url: str) -> bool:
    scheme, sep, rest = url.partition(":")
    return bool(sep) and bool(rest) and scheme.lower() in OPENABLE_SCHEMES


def paragraph_at(rows: list[str], width: int, row: int) -> tuple[str, int]:
    """Rebuild the logical line containing `row`.

    Returns the joined text and the offset at which `row` starts inside
    it. Rows exactly `width` wide are treated as continued, which is how
    tmux renders a wrapped line.
    """
    if row < 0 or row >= len(rows):
        return "", 0
    start = row
    while start > 0 and len(rows[start - 1]) >= width:
        start -= 1
    end = row
    while end < len(rows) - 1 and len(rows[end]) >= width:
        end += 1
    text = "".join(rows[start : end + 1])
    offset = sum(len(rows[i]) for i in range(start, row))
    return text, offset


def find_url(rows: list[str], width: int, row: int, col: int) -> str | None:
    """Return the URL under (row, col), or None.

    `rows` are one pane's screen rows with trailing blanks trimmed, as
    `tmux capture-pane -p` gives them. `col` is a column within the pane.
    """
    if width <= 0:
        return None
    text, offset = paragraph_at(rows, width, row)
    if not text:
        return None
    click = offset + col
    for m in _URL_RE.finditer(text):
        url = _trim(m.group(0))
        if not url:
            continue
        # finditer's span covers the untrimmed match; a click on the
        # punctuation we just dropped should not count as a hit.
        if m.start() <= click < m.start() + len(url):
            return url
    return None
