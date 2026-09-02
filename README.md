# bobbler

iPod `.scrobbler.log` editor and Last.fm submission tool.

Automatically detects a connected iPod, shows a popup to confirm submission, and scrobbles your plays to Last.fm. Includes a full GUI editor for fixing timestamps and album runs caused by iPod clock resets.

## Install

```bash
pipx install git+https://github.com/skeeeee/bobbler
```

Or with pip:

```bash
pip install git+https://github.com/skeeeee/bobbler
```

## First run

```bash
scrobbler --save-creds
```

Saves your Last.fm username, password, and timezone offset to `~/.scrobbler.cfg`.

## Usage

```bash
# Auto-detect .scrobbler.log on connected iPod and submit
bobbler

# Specify a file manually
scrobbler -p /path/to/.scrobbler.log

# Preview without submitting
scrobbler --dry-run

# Open the GUI editor
scrobbler -e

# Submit with timezone offset (if iPod clock is in local time, not UTC)
scrobbler --tz 8
```

## Background watcher (auto-popup on connect)

```bash
# Install as a login startup item
scrobbler-watch --install

# Remove startup item
scrobbler-watch --uninstall

# Run manually
scrobbler-watch
```

Once installed, connecting your iPod will automatically show a popup asking whether to submit scrobbles or open the editor.

## Update

```bash
pipx upgrade bobbler
```

## Requirements

- Python 3.10+
- No third-party dependencies (stdlib only)
- tkinter (included with most Python installs; on Linux: `sudo apt install python3-tk`)
