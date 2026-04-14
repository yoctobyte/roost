#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

die() { echo "conbrowse: $*" >&2; exit 1; }

command -v tmux >/dev/null 2>&1 \
  || die "tmux not found. Install it (e.g. 'sudo apt install tmux')."

command -v python3 >/dev/null 2>&1 \
  || die "python3 not found."

if [ ! -d "$VENV" ]; then
  echo "conbrowse: creating venv at $VENV"
  python3 -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  if [ -s "$HERE/requirements.txt" ]; then
    "$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"
  fi
fi

"$VENV/bin/python" - <<'PY' || die "GTK3/VTE bindings missing. On Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91"
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte  # noqa: F401
PY

export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m conbrowse "$@"
