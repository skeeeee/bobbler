# bobbler

iPod `.scrobbler.log` editor and Last.fm submission tool. Two packages in one repo:

| Package | Description | Install |
|---|---|---|
| `bobbler` | CLI tool + terminal watcher | `pip install "bobbler @ git+https://github.com/skeeeee/bobbler#subdirectory=bobbler"` |
| `bobbler-tray` | Silent system tray app | `pip install "bobbler-tray @ git+https://github.com/skeeeee/bobbler#subdirectory=bobbler-tray"` |

---

## bobbler (CLI)

```bash
pip install "bobbler @ git+https://github.com/skeeeee/bobbler#subdirectory=bobbler"

bobbler --save-creds     # first time setup
bobbler                  # auto-detect iPod and submit
bobbler --dry-run        # preview without submitting
bobbler -e               # open GUI editor
bobbler -p <file>        # specify log file manually
bobbler --tz 8           # apply UTC+8 offset before submitting
bobbler-watch            # terminal watcher (needs window open)
```

## bobbler-tray (system tray)

Runs silently in the background. Shows a popup when your iPod is connected.

```bash
pip install "bobbler-tray @ git+https://github.com/skeeeee/bobbler#subdirectory=bobbler-tray"

bobbler-tray             # start (right-click icon → Start with system to enable autostart)
```

Installs `bobbler` automatically as a dependency.

---

## Requirements

- Python 3.10+
- `bobbler-tray` additionally requires `pystray` and `Pillow` (installed automatically)
- tkinter — included with most Python installs. On Linux: `sudo apt install python3-tk`
