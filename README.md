# roost

> **roost** *(noun)*  a place where birds settle to rest, and the place
> they instinctively return to. *(verb)*  to settle down for the night.
>
> Your shell sessions are birds. They fly off doing things — long
> builds, ssh tunnels, half-finished `vim` buffers — and they need
> somewhere to come home to. **roost** is that place.

A small GTK desktop app that gives a single window onto many persistent
shell sessions. The sessions live in `tmux`, so they survive closing
the GUI, crashing the GUI, logging out, or attaching from a separate
ssh on the side. The GUI is just a comfortable way to see them all and
jump between them.

---

## Why

Half the terminals you have open right now are doing something you
care about and the other half are noise. They all live in their own
desktop window, scattered across workspaces, and the moment you close
the wrong one you lose state.

`tmux` already solves the persistence problem perfectly. It just
doesn't solve the *finding the right session* problem — that's what
the desktop window manager was supposed to do, and it's bad at it.

**roost** sits between you and tmux:

- one application window, one taskbar entry, one icon to pin
- an **overview page** with a tile per tmux window so you can see them
  all at a glance
- one tab per tmux window, click to jump in
- close the GUI and your shells keep running; reopen and they're all
  still there
- normal `tmux` from a shell or ssh keeps working — roost is just
  another client

---

## Install

Tested on Ubuntu 24.04. Should work on any reasonably recent
Debian-family distro.

```bash
sudo apt install tmux python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91
git clone https://github.com/yoctobyte/roost.git
cd roost
./run.sh
```

That's it. `run.sh` will:

1. create a virtualenv with `--system-site-packages` so it can see the
   distro's PyGObject (GTK and VTE are not installable from pip)
2. verify the GTK 3 + VTE 2.91 bindings are importable
3. install a `.desktop` entry into `~/.local/share/applications/` and
   the application icon into `~/.local/share/icons/hicolor/scalable/apps/`
4. launch the app

The `.desktop` install is idempotent and re-runs cheaply, so move the
checkout wherever you like — the next launch updates the paths.

### Pinning to the dash

After the first launch, open the GNOME Activities grid, search for
"roost", right-click the icon, and pick *Pin to Dash*. From then on,
clicking the dash icon launches the app and the running window
re-attaches to that tile.

---

## Usage

When roost starts you land on the **Overview** page — a grid of cards,
one per tmux window, each showing the window's name, index, and a
miniature preview of its contents.

- Click a card to jump into that window's tab.
- Click the **New** button (or `Ctrl+Shift+T`) to create a new console.
- Click the **Overview** button (or `Ctrl+Shift+O`) to come back.
- Click the per-window tabs in the strip below the header to switch.
- Hover any tab to see the full window name, the current command, the
  current working directory, and the last few lines of output.

### Keyboard shortcuts

| Shortcut             | Action                       |
|----------------------|------------------------------|
| `Ctrl+Shift+T`       | New console                  |
| `Ctrl+Shift+W`       | Close current console        |
| `Ctrl+Shift+R`       | Rename current console       |
| `Ctrl+Shift+O`       | Show overview                |
| `F5`                 | Refresh                      |
| `Ctrl+Shift+C`       | Copy selection in terminal   |
| `Ctrl+Shift+V`       | Paste into terminal          |
| `Ctrl+Insert`        | Copy (X11 classic)           |
| `Shift+Insert`       | Paste (X11 classic)          |

The tmux **prefix key** (default `Ctrl+B`) is forwarded to tmux
unchanged, so you can drive tmux normally from inside the embedded
terminal — `Ctrl+B C` opens a tmux window, `Ctrl+B ,` renames, and so
on. roost's window list will pick up the changes on the next sync.

### Right-click menu in the terminal

Right-click anywhere in the terminal pane for **Copy**, **Paste**, and
**Select All**. Copy is greyed out when nothing is selected.

---

## Preferences

Click the gear icon in the header bar (or open the Preferences menu)
to set:

- **Overview font size** (2–14 pt). The default is 4pt — the whole
  point of the overview is to fit a lot of state into a small card,
  so the font is intentionally tiny. Bump it up if your eyes object.
- **Theme** — Ubuntu Brown (default), Black, White, or Soft White.
  The theme applies to the embedded terminal *and* the overview cards.

Settings are written to `~/.config/roost/settings.json` and re-read on
next launch.

---

## How it works

The design in [`design.md`](design.md) has the long version. The short
version:

- **tmux is authoritative.** roost owns no shell processes, no ptys,
  no session state. Every window you see in the GUI is a real
  `tmux` window in the managed session (default name: `roost`).
- **One VTE, not many.** A single `Vte.Terminal` widget runs `tmux
  attach` once at startup. Switching tabs in the GUI calls `tmux
  select-window`, and the attached client follows. This avoids the
  size-negotiation mess you get when multiple tmux clients fight over
  the same session.
- **Overview previews come from `tmux capture-pane`**, not from N
  parallel terminal emulators. Cheap, fast, no flicker.
- **Sync is polling-based** at ~1.5 s. Adequate for the use case;
  control-mode (`tmux -C`) is on the roadmap as a drop-in upgrade.

---

## Compatibility

If it works under tmux, it works in roost. That covers basically the
entire Unix TUI catalogue: `vim`, `emacs`, `htop`, `less`, `man`,
`ranger`, `mc`, `nnn`, `ssh`, `mosh`, `nano`, `tig`, `lazygit`, `top`,
`btop`, language REPLs, you name it.

The known weak spots are things that try to talk to the terminal
*below* tmux's abstraction layer:

- sixel image protocols
- the kitty graphics protocol
- terminal-side GPU overlays
- true-color probes that some apps use to feature-detect

These degrade (no images, fewer colors) but don't break the app.

---

## Troubleshooting

**"GTK3/VTE bindings missing"** at launch — install the apt packages
listed under [Install](#install). The check runs every launch, not
just on first run, so a distro upgrade that breaks the bindings is
caught immediately.

**"tmux session lost" dialog** — your managed `roost` tmux session
was killed externally (e.g. someone ran `tmux kill-session -t roost`).
roost will not silently recreate it. Close the dialog and relaunch;
roost will start a fresh session.

**Empty overview after startup** — the managed session was just
created and only contains a single `bash` shell. Press *New* a few
times, or run `tmux new-window -t =roost` from another shell, and
the cards will appear.

**Right-click does nothing in the terminal** — make sure you're
right-clicking *inside* the terminal area, not on the header or tab
strip.

---

## Status

This is **v0.1** — usable daily, the design holds together, and the
author runs roost inside roost. Things on the roadmap:

- control-mode sync (event-driven instead of polling)
- activity badges per window
- freeze / hold view
- optional secondary VTE pane via tmux *grouped sessions*
- non-Debian package-name hints in `run.sh`

---

## License

[MIT](LICENSE).
