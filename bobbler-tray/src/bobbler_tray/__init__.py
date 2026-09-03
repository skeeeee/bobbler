#!/usr/bin/env python3
"""
bobbler_tray — system tray app for bobbler

Runs silently in the background as a system tray icon.
Monitors for external drives with .scrobbler.log and shows a popup when found.

Usage:
  bobbler-tray              # start the tray app
  bobbler-tray --install    # install as Windows startup item
  bobbler-tray --uninstall  # remove startup item
"""

import argparse
import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Missing dependencies. Run: pip install pystray Pillow")
    sys.exit(1)

POLL_INTERVAL = 2
LOG_FILENAME  = ".scrobbler.log"

# ── Icon image (generated, no file needed) ────────────────────────────────────
def make_icon_image(size=64) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Purple circle background
    draw.ellipse([2, 2, size-2, size-2], fill=(192, 132, 252, 255))
    # White music note
    cx, cy = size // 2, size // 2
    r = size // 8
    # Note head
    draw.ellipse([cx-r, cy+r, cx+r, cy+r*3], fill=(255, 255, 255, 255))
    # Note stem
    draw.rectangle([cx+r-2, cy-r*3, cx+r+2, cy+r*2], fill=(255, 255, 255, 255))
    # Note flag
    draw.polygon([cx+r, cy-r*3, cx+r*4, cy-r, cx+r, cy-r], fill=(255, 255, 255, 255))
    return img

# ── Drive detection ───────────────────────────────────────────────────────────
def find_drives_with_log() -> list[Path]:
    import glob, string
    system = platform.system()
    logs   = []

    if system == "Windows":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drive = Path(f"{letter}:\\")
                dtype = ctypes.windll.kernel32.GetDriveTypeW(str(drive))
                if dtype == 2 or (dtype == 3 and letter.upper() != "C"):
                    log = drive / LOG_FILENAME
                    if log.exists():
                        logs.append(log)

    elif system == "Darwin":
        volumes = Path("/Volumes")
        if volumes.exists():
            for p in volumes.iterdir():
                if p.is_dir() and p.name != "Macintosh HD":
                    log = p / LOG_FILENAME
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
                    log = Path(p) / LOG_FILENAME
                    if log.exists():
                        logs.append(log)

    return logs

# ── Popup ─────────────────────────────────────────────────────────────────────
def show_popup(log_path: Path) -> str | None:
    BAD_TS = 978307200
    total = eligible = bad = 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or not line.strip(): continue
                parts = line.split("\t")
                if len(parts) < 7: continue
                try: ts = int(parts[6])
                except ValueError: continue
                total += 1
                if ts < BAD_TS: bad += 1
                elif parts[5] != "S": eligible += 1
    except OSError:
        return None

    if total == 0:
        return None

    result = {"action": None}

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    popup = tk.Toplevel(root)
    popup.title("Bobbler")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    w, h = 380, 230
    sw = popup.winfo_screenwidth()
    sh = popup.winfo_screenheight()
    popup.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    tk.Label(popup, text="🎵  iPod detected", font=("Helvetica", 13, "bold"), pady=12).pack()
    tk.Label(popup, text=log_path.parent.name or str(log_path.parent),
             fg="#6b7280", font=("Helvetica", 10)).pack()

    stats = f"{eligible} scrobbles ready to submit"
    if bad: stats += f"  ·  {bad} with bad dates (excluded)"
    tk.Label(popup, text=stats, font=("Helvetica", 10), pady=8).pack()

    edit_var = tk.BooleanVar(value=False)
    tk.Checkbutton(popup, text="Open editor instead of auto-submitting",
                   variable=edit_var, font=("Helvetica", 10)).pack(pady=4)

    def on_yes():
        result["action"] = "edit" if edit_var.get() else "submit"
        popup.destroy()
        root.destroy()

    def on_no():
        result["action"] = "skip"
        popup.destroy()
        root.destroy()

    popup.protocol("WM_DELETE_WINDOW", on_no)

    btn_frame = tk.Frame(popup)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="Yes", width=10, bg="#c084fc", fg="white",
              font=("Helvetica", 10, "bold"), command=on_yes).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="No",  width=10,
              font=("Helvetica", 10), command=on_no).pack(side=tk.LEFT, padx=8)

    root.mainloop()
    return result["action"]

# ── Launch bobbler ────────────────────────────────────────────────────────────
def get_bobbler_cmd() -> list[str]:
    import shutil
    ep = shutil.which("bobbler")
    if ep:
        return [ep]
    raise FileNotFoundError("bobbler not found. Install it with: pip install bobbler")

def launch(action: str, log_path: Path):
    try:
        cmd = get_bobbler_cmd() + ["-p", str(log_path)]
    except FileNotFoundError as e:
        messagebox.showerror("Bobbler", str(e))
        return
    if action == "edit":
        cmd.append("-e")
    subprocess.Popen(cmd)

# ── Watcher thread ────────────────────────────────────────────────────────────
def watcher_thread(icon: pystray.Icon):
    seen      = set()
    first_run = True

    while True:
        try:
            current = {str(p) for p in find_drives_with_log()}
            if first_run:
                seen      = current.copy()
                first_run = False
            else:
                for log_str in current - seen:
                    seen.add(log_str)
                    threading.Thread(
                        target=handle_new_log,
                        args=(Path(log_str),),
                        daemon=True
                    ).start()
                seen &= current
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)

def handle_new_log(log_path: Path):
    action = show_popup(log_path)
    if action in ("submit", "edit"):
        launch(action, log_path)

# ── Autostart ─────────────────────────────────────────────────────────────────
def is_autostart_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, "BobblerTray")
            return True
        except FileNotFoundError:
            return False
    elif system == "Darwin":
        return (Path.home() / "Library/LaunchAgents/com.bobbler.tray.plist").exists()
    else:
        return (Path.home() / ".config/autostart/bobbler-tray.desktop").exists()

def toggle_autostart(icon, item):
    if is_autostart_enabled():
        uninstall_autostart()
    else:
        install_autostart()
    # Refresh menu to reflect new state
    icon.menu = build_menu()
    icon.update_menu()

def build_menu() -> pystray.Menu:
    enabled = is_autostart_enabled()
    label   = "✓ Start with system" if enabled else "Start with system"
    return pystray.Menu(
        pystray.MenuItem("Bobbler — watching for iPod…", lambda: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(label, toggle_autostart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: icon.stop()),
    )

def install_autostart():
    system = platform.system()
    script = Path(sys.executable).parent / "Scripts" / "bobbler-tray.exe" \
        if system == "Windows" else Path(sys.executable).parent / "bobbler-tray"

    if system == "Windows":
        import winreg
        cmd = f'"{script}"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "BobblerTray", 0, winreg.REG_SZ, cmd)
            print(f"Installed startup entry:\n  {cmd}")
        except Exception as e:
            print(f"Failed: {e}")

    elif system == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/com.bobbler.tray.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.bobbler.tray</string>
    <key>ProgramArguments</key>
    <array><string>{sys.executable}</string><string>-m</string><string>bobbler_tray</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>"""
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist)
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print(f"Installed: {plist_path}")

    else:  # Linux XDG
        desktop_path = Path.home() / ".config/autostart/bobbler-tray.desktop"
        desktop = f"""[Desktop Entry]
Type=Application
Name=Bobbler Tray
Exec={sys.executable} -m bobbler_tray
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Bobbler system tray — monitors for iPod and auto-submits scrobbles
"""
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(desktop)
        print(f"Installed: {desktop_path}")

def uninstall_autostart():
    system = platform.system()
    if system == "Windows":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "BobblerTray")
            print("Removed startup entry.")
        except FileNotFoundError:
            print("No startup entry found.")
        except Exception as e:
            print(f"Failed: {e}")
    elif system == "Darwin":
        p = Path.home() / "Library/LaunchAgents/com.bobbler.tray.plist"
        if p.exists():
            subprocess.run(["launchctl", "unload", str(p)], check=False)
            p.unlink(); print(f"Removed: {p}")
        else:
            print("No startup entry found.")
    else:
        p = Path.home() / ".config/autostart/bobbler-tray.desktop"
        if p.exists():
            p.unlink(); print(f"Removed: {p}")
        else:
            print("No startup entry found.")

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="bobbler-tray",
        description="Bobbler system tray app — monitors for iPod in the background"
    )
    parser.add_argument("--install",   action="store_true", help="Install as startup item")
    parser.add_argument("--uninstall", action="store_true", help="Remove startup item")
    args = parser.parse_args()

    if args.install:
        install_autostart()
        return
    if args.uninstall:
        uninstall_autostart()
        return

    icon_image = make_icon_image()

    icon = pystray.Icon(
        name="bobbler",
        icon=icon_image,
        title="Bobbler",
        menu=build_menu(),
    )

    # Start watcher in background thread
    t = threading.Thread(target=watcher_thread, args=(icon,), daemon=True)
    t.start()

    # Run tray icon (blocks until quit)
    icon.run()

def cli():
    main()

if __name__ == "__main__":
    main()
