#!/usr/bin/env python3
"""
bobbler_watch.py — background watcher daemon

Monitors for new external drives. When a drive with .scrobbler.log appears,
shows a popup asking whether to submit. Runs silently in the background.

Usage:
  python bobbler_watch.py              # start watcher
  python bobbler_watch.py --install    # install as autostart on login
  python bobbler_watch.py --uninstall  # remove autostart entry
"""

import argparse
import os
import platform
import subprocess
import sys
import time
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

# ── Locate bobbler entry point ───────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent.resolve()
BOBBLER_PY    = SCRIPT_DIR / "bobbler.py"
POLL_INTERVAL = 2

def get_bobbler_cmd() -> list[str]:
    import shutil
    ep = shutil.which("bobbler")
    if ep:
        return [ep]
    if BOBBLER_PY.exists():
        return [sys.executable, str(BOBBLER_PY)]
    raise FileNotFoundError("Cannot find bobbler. Is the package installed?")

# ── Drive detection (mirrors bobbler.py) ────────────────────────────────────
def find_drives_with_log() -> list[Path]:
    """Return paths to .scrobbler.log files on all currently mounted drives."""
    import glob
    import string

    system  = platform.system()
    logs    = []

    if system == "Windows":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drive = Path(f"{letter}:\\")
                dtype = ctypes.windll.kernel32.GetDriveTypeW(str(drive))
                if dtype == 2 or (dtype == 3 and letter.upper() != "C"):
                    log = drive / ".scrobbler.log"
                    if log.exists():
                        logs.append(log)

    elif system == "Darwin":
        volumes = Path("/Volumes")
        if volumes.exists():
            for p in volumes.iterdir():
                if p.is_dir() and p.name != "Macintosh HD":
                    log = p / ".scrobbler.log"
                    if log.exists():
                        logs.append(log)

    else:  # Linux
        username = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        patterns = [
            "/media/*/*", f"/media/{username}/*",
            "/run/media/*/*", f"/run/media/{username}/*",
            "/mnt/*",
        ]
        seen = set()
        for pat in patterns:
            for p in glob.glob(pat):
                rp = os.path.realpath(p)
                if rp not in seen and os.path.isdir(p):
                    seen.add(rp)
                    log = Path(p) / ".scrobbler.log"
                    if log.exists():
                        logs.append(log)

    return logs

# ── Popup ─────────────────────────────────────────────────────────────────────
def show_popup(log_path: Path):
    """Show the yes/no/edit popup for a detected .scrobbler.log."""

    # Count eligible scrobbles quickly without importing full bobbler
    BAD_TS = 978307200
    total, eligible, bad = 0, 0, 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                try:
                    ts = int(parts[6])
                except ValueError:
                    continue
                total += 1
                if ts < BAD_TS:
                    bad += 1
                elif parts[5] != "S":
                    eligible += 1
    except OSError:
        return

    if total == 0:
        return  # empty log, ignore silently

    root = tk.Tk()
    root.withdraw()  # hide root window
    root.attributes("-topmost", True)

    popup = tk.Toplevel(root)
    popup.title("Bobbler")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    # Center on screen
    popup.update_idletasks()
    w, h = 360, 220
    sw = popup.winfo_screenwidth()
    sh = popup.winfo_screenheight()
    popup.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # Icon-ish header
    tk.Label(popup, text="🎵  iPod detected", font=("Helvetica", 13, "bold"),
             pady=12).pack()

    drive_name = log_path.parent.name or str(log_path.parent)
    tk.Label(popup, text=f"{drive_name}", fg="#6b7280", font=("Helvetica", 10)).pack()

    # Stats
    stats = f"{eligible} scrobbles ready to submit"
    if bad:
        stats += f"  ·  {bad} with bad dates (excluded)"
    tk.Label(popup, text=stats, font=("Helvetica", 10), pady=8).pack()

    # Edit checkbox
    edit_var = tk.BooleanVar(value=False)
    tk.Checkbutton(popup, text="Open editor instead of auto-submitting",
                   variable=edit_var, font=("Helvetica", 10)).pack(pady=4)

    result = {"action": None}

    def on_yes():
        result["action"] = "edit" if edit_var.get() else "submit"
        popup.destroy()
        root.destroy()

    def on_no():
        result["action"] = "skip"
        popup.destroy()
        root.destroy()

    # Bind close button to "no"
    popup.protocol("WM_DELETE_WINDOW", on_no)

    btn_frame = tk.Frame(popup)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="Yes", width=10, bg="#c084fc", fg="white",
              font=("Helvetica", 10, "bold"), command=on_yes).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="No", width=10,
              font=("Helvetica", 10), command=on_no).pack(side=tk.LEFT, padx=8)

    root.mainloop()

    return result["action"]

# ── Launch action ─────────────────────────────────────────────────────────────
def launch(action: str, log_path: Path):
    try:
        cmd = get_bobbler_cmd() + ["-p", str(log_path)]
    except FileNotFoundError as e:
        messagebox.showerror("Error", str(e))
        return
    if action == "edit":
        cmd.append("-e")
    subprocess.Popen(cmd)

# ── Watcher loop ──────────────────────────────────────────────────────────────
def watch():
    seen      = set()   # log paths already handled this session
    first_run = True    # ignore drives present at startup

    while True:
        try:
            current_logs = {str(p) for p in find_drives_with_log()}

            if first_run:
                seen      = current_logs.copy()
                first_run = False
            else:
                new_logs = current_logs - seen
                for log_str in new_logs:
                    log_path = Path(log_str)
                    seen.add(log_str)
                    # Run popup in its own thread so the watcher keeps polling
                    t = threading.Thread(target=handle_new_log, args=(log_path,), daemon=True)
                    t.start()

                # Remove disconnected drives from seen so reconnecting works
                seen &= current_logs

        except Exception:
            pass  # never crash the watcher

        time.sleep(POLL_INTERVAL)

def handle_new_log(log_path: Path):
    action = show_popup(log_path)
    if action in ("submit", "edit"):
        launch(action, log_path)

# ── Autostart install/uninstall ───────────────────────────────────────────────
def install_autostart():
    system = platform.system()
    script = Path(__file__).resolve()
    py     = sys.executable

    if system == "Windows":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        cmd      = f'"{py}" "{script}"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "BobblerWatch", 0, winreg.REG_SZ, cmd)
            print(f"Installed autostart (Registry):\n  {cmd}")
        except Exception as e:
            print(f"Failed to install: {e}")

    elif system == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/com.bobbler.watch.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bobbler.watch</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py}</string>
        <string>{script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>"""
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist)
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print(f"Installed autostart: {plist_path}")

    else:  # Linux — XDG autostart
        autostart_dir  = Path.home() / ".config/autostart"
        desktop_path   = autostart_dir / "bobbler-watch.desktop"
        desktop = f"""[Desktop Entry]
Type=Application
Name=Bobbler Watch
Exec={py} {script}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Watches for iPod and auto-submits scrobbles
"""
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(desktop)
        print(f"Installed autostart: {desktop_path}")

def uninstall_autostart():
    system = platform.system()

    if system == "Windows":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "BobblerWatch")
            print("Removed autostart entry.")
        except FileNotFoundError:
            print("No autostart entry found.")
        except Exception as e:
            print(f"Failed: {e}")

    elif system == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/com.bobbler.watch.plist"
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()
            print(f"Removed: {plist_path}")
        else:
            print("No autostart entry found.")

    else:
        desktop_path = Path.home() / ".config/autostart/bobbler-watch.desktop"
        if desktop_path.exists():
            desktop_path.unlink()
            print(f"Removed: {desktop_path}")
        else:
            print("No autostart entry found.")

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="bobbler_watch",
        description="Background watcher — shows popup when iPod with .scrobbler.log is connected"
    )
    parser.add_argument("--install",   action="store_true", help="Install as autostart on login")
    parser.add_argument("--uninstall", action="store_true", help="Remove autostart entry")
    args = parser.parse_args()

    if args.install:
        install_autostart()
        return
    if args.uninstall:
        uninstall_autostart()
        return

    print(f"Bobbler watcher running. Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.")
    try:
        watch()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()

def cli():
    main()
