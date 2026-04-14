# conbrowse

A GTK console browser over tmux. See `design.md` for the full design.

## Run

```
./run.sh
```

On first run the script creates a venv (with `--system-site-packages`
so it can see PyGObject), verifies that `tmux` and the GTK3/VTE
bindings are importable, and launches the app.

### System requirements (Ubuntu 24.04)

```
sudo apt install tmux python3-gi gir1.2-gtk-3.0 gir1.2-vte-2.91
```
