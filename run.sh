#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
APP_ID="org.roost.Roost"
XDG_DATA_HOME_="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP_DIR="$XDG_DATA_HOME_/applications"
ICON_DIR="$XDG_DATA_HOME_/icons/hicolor/scalable/apps"
DESKTOP_FILE="$DESKTOP_DIR/${APP_ID}.desktop"
ICON_FILE="$ICON_DIR/${APP_ID}.svg"

die() { echo "roost: $*" >&2; exit 1; }

install_desktop_entry() {
  local template="$HERE/data/${APP_ID}.desktop.in"
  local src_icon="$HERE/src/roost/icon.svg"
  [ -f "$template" ] || return 0
  [ -f "$src_icon" ] || return 0

  mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

  local icon_changed=0
  # Copy icon to the hicolor theme so the desktop entry can reference
  # it by symbolic name (Icon=org.roost.Roost).
  if [ ! -f "$ICON_FILE" ] || ! cmp -s "$src_icon" "$ICON_FILE"; then
    cp -- "$src_icon" "$ICON_FILE"
    icon_changed=1
  fi

  # Substitute @EXEC@ with the absolute path to this launcher.
  local exec_path="$HERE/run.sh"
  local tmp
  tmp="$(mktemp)"
  sed "s|@EXEC@|${exec_path//|/\\|}|g" "$template" > "$tmp"
  local desktop_changed=0
  if [ ! -f "$DESKTOP_FILE" ] || ! cmp -s "$tmp" "$DESKTOP_FILE"; then
    mv -- "$tmp" "$DESKTOP_FILE"
    chmod 644 "$DESKTOP_FILE"
    desktop_changed=1
    echo "roost: installed desktop entry at $DESKTOP_FILE"
  else
    rm -f -- "$tmp"
  fi

  if [ "$desktop_changed" -eq 1 ] \
     && command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
  fi

  # Rebuild the hicolor icon cache so shells that consult it (GNOME,
  # Cinnamon, KDE) find Icon=org.roost.Roost by name. --ignore-theme-index
  # is needed because the user hicolor tree usually has no local
  # index.theme file.
  if [ "$icon_changed" -eq 1 ] \
     && command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache --ignore-theme-index -f -q \
      "$XDG_DATA_HOME_/icons/hicolor" >/dev/null 2>&1 || true
  fi
}

command -v tmux >/dev/null 2>&1 \
  || die "tmux not found. Install it (e.g. 'sudo apt install tmux')."

command -v python3 >/dev/null 2>&1 \
  || die "python3 not found."

if [ ! -d "$VENV" ]; then
  echo "roost: creating venv at $VENV"
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

install_desktop_entry

export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m roost "$@"
