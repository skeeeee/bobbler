# bobbler-tray

System tray app for [bobbler](https://github.com/skeeeee/bobbler).

Runs silently in the background. When you connect your iPod, a popup appears asking whether to submit your scrobbles or open the editor. No terminal needed.

## Install

```bash
pip install git+https://github.com/skeeeee/bobbler-tray
```

This also installs `bobbler` and its dependencies automatically.

## Setup

```bash
# Install as a startup item (runs automatically on login)
bobbler-tray --install

# Start manually (this session only)
bobbler-tray
```

## Usage

Once running, bobbler-tray lives in your system tray (bottom-right on Windows). Right-click the icon to quit.

When an iPod with a `.scrobbler.log` file is connected, a popup appears:

- **Yes** — submits scrobbles via `bobbler`
- **Yes + "Open editor"** — opens the bobbler GUI editor
- **No** — dismisses, does nothing

## Remove startup item

```bash
bobbler-tray --uninstall
```

## Requirements

- Python 3.10+
- [bobbler](https://github.com/skeeeee/bobbler)
- pystray
- Pillow
