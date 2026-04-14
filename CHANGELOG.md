# Changelog

## v0.1.0 — 2026-04-14

First public release. The project was previously developed under the
working name **conbrowse** and renamed to **roost** for v0.1.

### Features

- Single GTK 3 window onto a managed `tmux` session.
- Overview page with one card per tmux window, showing name, index,
  and a tiny live preview of the contents.
- Per-window tab strip; click to switch, `Ctrl+Shift+T/W/R/O` and
  `F5` for new / close / rename / overview / refresh.
- One persistent `Vte.Terminal` running `tmux attach`. Tab switches
  call `tmux select-window`; the attached client follows.
- Right-click context menu in the terminal: Copy / Paste / Select All.
  `Ctrl+Shift+C/V` and `Ctrl+Insert` / `Shift+Insert` also work.
- Preferences dialog: overview font size (2–14 pt) and theme picker
  (Ubuntu Brown / Black / White / Soft White). Settings persist to
  `~/.config/roost/settings.json`.
- First-run installer: `run.sh` writes a `.desktop` entry and a
  themed icon to `~/.local/share/`, so the app can be pinned to the
  GNOME dash.
- Polling sync against external `tmux` changes (default 1.5 s).

### Migrating from `conbrowse`

If you used the project under its old name:

- The tmux session was renamed from `console-browser` to `roost`.
  To preserve your existing windows, run once from any shell:
  ```
  tmux rename-session -t console-browser roost
  ```
- The settings file moved from `~/.config/conbrowse/settings.json` to
  `~/.config/roost/settings.json`. Either copy it across or
  re-configure from the Preferences dialog.
- The desktop file moved from `org.conbrowse.Conbrowse.desktop` to
  `org.roost.Roost.desktop`. The first launch of the renamed app
  installs the new file; the old one can be deleted by hand.
