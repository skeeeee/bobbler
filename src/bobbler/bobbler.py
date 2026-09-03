#!/usr/bin/env python3
"""
bobbler.py — iPod .scrobbler.log CLI & GUI tool

Default mode: auto-detects .scrobbler.log on a connected external drive.

Usage:
  python bobbler.py                             # auto-detect log on external drive
  python bobbler.py -p /path/to/.scrobbler.log  # manual path
  python bobbler.py -e                          # open GUI editor (auto-detects log)
  python bobbler.py -p <file> -e               # open GUI editor with specific file
  python bobbler.py --tz 8                      # submit with UTC+8 offset applied
  python bobbler.py --dry-run                   # preview without submitting
  python bobbler.py --save-creds               # save credentials to ~/.bobbler.cfg
  python bobbler.py --keep                      # do not delete log file after submitting
"""

import argparse
import configparser
import getpass
import glob
import json
import hashlib
import os
import platform
import string
import sys
import urllib.parse
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
BAD_TS       = 978307200
RUN_DELTA    = 65
LFM_API_URL  = "https://ws.audioscrobbler.com/2.0/"
CONFIG_PATH  = Path.home() / ".bobbler.cfg"
LOG_FILENAME = ".scrobbler.log"
LFM_API_KEY    = "28c0154f421917604411cfa95131a21d"
LFM_API_SECRET = "9ae5f35e884187c50cb315d550b183bc"

# ── Drive detection ───────────────────────────────────────────────────────────
def find_external_drives() -> list[Path]:
    system = platform.system()
    roots  = []
    if system == "Windows":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drive = Path(f"{letter}:\\")
                dtype = ctypes.windll.kernel32.GetDriveTypeW(str(drive))
                if dtype == 2 or (dtype == 3 and letter.upper() != "C"):
                    roots.append(drive)
    elif system == "Darwin":
        volumes = Path("/Volumes")
        if volumes.exists():
            roots = [p for p in volumes.iterdir() if p.is_dir() and p.name != "Macintosh HD"]
    else:  # Linux
        username = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        patterns = ["/media/*/*", f"/media/{username}/*", "/run/media/*/*", f"/run/media/{username}/*", "/mnt/*"]
        seen = set()
        for pat in patterns:
            for p in glob.glob(pat):
                rp = os.path.realpath(p)
                if rp not in seen and os.path.isdir(p):
                    seen.add(rp)
                    roots.append(Path(p))
    return roots

def find_log_on_drives() -> Path | None:
    drives = find_external_drives()
    candidates = [drive / LOG_FILENAME for drive in drives if (drive / LOG_FILENAME).exists()]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print("Multiple .scrobbler.log files found:")
        for i, c in enumerate(candidates):
            print(f"  [{i+1}] {c}")
        choice = input("Choose [1]: ").strip()
        idx = int(choice) - 1 if choice.isdigit() else 0
        return candidates[max(0, min(idx, len(candidates)-1))]
    return None

def resolve_log(args) -> Path:
    if args.path:
        p = Path(args.path)
        if not p.exists():
            print(f"Error: file not found: {p}")
            sys.exit(1)
        return p
    print("Searching for .scrobbler.log on external drives…")
    log = find_log_on_drives()
    if log:
        print(f"Found: {log}")
        return log
    drives = find_external_drives()
    if drives:
        print(f"No .scrobbler.log found on: {', '.join(str(d) for d in drives)}")
    else:
        print("No external drives detected.")
    print(f"Use -p <path> to specify the file manually.")
    sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────
def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def build_sig(params: dict, secret: str) -> str:
    keys = sorted(k for k in params if k != "format")
    raw  = "".join(k + str(params[k]) for k in keys) + secret
    return md5(raw)

def ts_to_str(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def fmt_dur(s: int) -> str:
    return f"{s//60}:{s%60:02d}"

# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    return cfg

def save_config(cfg: configparser.ConfigParser):
    if "lastfm" not in cfg:
        cfg["lastfm"] = {}
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)
    CONFIG_PATH.chmod(0o600)

def get_creds(args, cfg) -> dict:
    section  = cfg["lastfm"] if "lastfm" in cfg else {}
    username = args.username or section.get("username") or input("Last.fm username: ").strip()
    password = args.password or section.get("password") or getpass.getpass("Last.fm password: ")
    return {"api_key": LFM_API_KEY, "api_secret": LFM_API_SECRET, "username": username, "password": password}

def save_creds_interactive():
    cfg = load_config()
    if "lastfm" not in cfg:
        cfg["lastfm"] = {}
    cfg["lastfm"]["username"] = input("Last.fm username: ").strip()
    cfg["lastfm"]["password"] = getpass.getpass("Last.fm password: ")
    tz = input("Default TZ offset (e.g. 8 for UTC+8, 0 for none) [0]: ").strip()
    cfg["lastfm"]["tz_offset"] = tz if tz.lstrip("-").isdigit() else "0"
    save_config(cfg)
    print(f"Saved to {CONFIG_PATH}")

def prompt_and_save_creds(cfg) -> dict:
    print("No saved credentials found. Let's set them up.\n")
    if "lastfm" not in cfg:
        cfg["lastfm"] = {}
    cfg["lastfm"]["username"] = input("Last.fm username: ").strip()
    cfg["lastfm"]["password"] = getpass.getpass("Last.fm password: ")
    tz = input("Default TZ offset (e.g. 8 for UTC+8, 0 for none) [0]: ").strip()
    cfg["lastfm"]["tz_offset"] = tz if tz.lstrip("-").isdigit() else "0"
    save_config(cfg)
    print(f"Credentials saved to {CONFIG_PATH}. You won't be asked again.\n")
    return cfg

# ── Parse & Analyze ───────────────────────────────────────────────────────────
def parse_log(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or not line.strip(): continue
            parts = line.split("\t")
            if len(parts) < 7: continue
            try:
                ts = int(parts[6])
            except ValueError: continue
            rows.append({
                "artist": parts[0], "album": parts[1], "track": parts[2],
                "num": int(parts[3]) if parts[3].isdigit() else 0,
                "dur": int(parts[4]) if parts[4].isdigit() else 0,
                "rating": parts[5], "ts": ts,
                "mbid": parts[7] if len(parts) > 7 else "",
                "file_idx": len(rows), "original_ts": ts,
                "edited": False, "overlap": False, "bad_date": ts < BAD_TS, "run_id": None
            })
    return build_chains(rows)

def build_chains(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["run_id"] = None
        r["overlap"] = False
        r["bad_date"] = r["ts"] < BAD_TS

    by_key = {}
    for r in rows:
        k = (r["artist"], r["album"], r["num"])
        by_key.setdefault(k, []).append(r)

    visited = set()
    run_counter = 0
    sorted_rows = sorted(rows, key=lambda x: x["ts"])

    for anchor in sorted_rows:
        if id(anchor) in visited: continue
        
        prev_k = (anchor["artist"], anchor["album"], anchor["num"] - 1)
        has_pred = any(id(p) not in visited and abs(p["ts"] + p["dur"] - anchor["ts"]) <= RUN_DELTA for p in by_key.get(prev_k, []))
        if has_pred: continue

        chain = [anchor]
        visited.add(id(anchor))
        cur = anchor

        while True:
            next_k = (cur["artist"], cur["album"], cur["num"] + 1)
            candidates = by_key.get(next_k, [])
            expected = cur["ts"] + cur["dur"]
            best, best_delta = None, float('inf')
            for c in candidates:
                if id(c) in visited: continue
                d = abs(c["ts"] - expected)
                if d <= RUN_DELTA and d < best_delta:
                    best, best_delta = c, d
            if not best: break
            visited.add(id(best))
            chain.append(best)
            cur = best

        if len(chain) > 1:
            for r in chain: r["run_id"] = run_counter
            run_counter += 1

    by_ts = sorted(rows, key=lambda x: x["ts"])
    for i in range(len(by_ts) - 1):
        if by_ts[i]["ts"] + by_ts[i]["dur"] > by_ts[i+1]["ts"]:
            by_ts[i]["overlap"] = True
            by_ts[i+1]["overlap"] = True

    return rows

def eligible(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r["bad_date"] and r["rating"] != "S"]

# ── Last.fm Auth & Submit ──────────────────────────────────────────────────────
def lfm_get_session(creds: dict) -> str:
    params = {"method": "auth.getMobileSession", "api_key": creds["api_key"], "username": creds["username"], "password": creds["password"]}
    params["api_sig"] = build_sig(params, creds["api_secret"])
    params["format"] = "json"
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(LFM_API_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    if "error" in data: raise RuntimeError(f"Auth error {data['error']}: {data['message']}")
    return data["session"]["key"]

def lfm_submit_batch(batch: list[dict], creds: dict, sk: str, tz: int) -> tuple[int, int, list[str]]:
    params = {"method": "track.scrobble", "api_key": creds["api_key"], "sk": sk}
    for j, r in enumerate(batch):
        params[f"artist[{j}]"] = r["artist"]
        params[f"track[{j}]"] = r["track"]
        params[f"album[{j}]"] = r["album"]
        params[f"timestamp[{j}]"] = r["ts"] - tz * 3600
        params[f"duration[{j}]"] = r["dur"]
    params["api_sig"] = build_sig(params, creds["api_secret"])
    params["format"] = "json"
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(LFM_API_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    if "error" in data: return 0, len(batch), [f"  API Error {data['error']}: {data['message']}"]
    attr = data.get("scrobbles", {}).get("@attr", {})
    accepted = int(attr.get("accepted", 0))
    ignored = int(attr.get("ignored", 0))
    errors = []
    sl = data.get("scrobbles", {}).get("scrobble", [])
    if isinstance(sl, dict): sl = [sl]
    for s in sl:
        code = str(s.get("ignoredMessage", {}).get("code", "0"))
        if code != "0":
            errors.append(f"  {s.get('artist',{}).get('#text','?')} — {s.get('track',{}).get('#text','?')}: Ignored (code {code})")
    return accepted, ignored, errors

def print_preview(rows: list[dict], tz: int, limit: int = 10):
    el = eligible(rows)
    if not el:
        print("No eligible scrobbles.")
        return

    print(f"\n{'─'*84}")
    print(f"  {'ARTIST':<26} {'TRACK':<28} {'STORED (UTC)':<22} {'SUBMITTED AS (UTC)'}")
    print(f"{'─'*84}")

    show = (el[:limit//2] + [None] + el[-(limit//2):]) if len(el) > limit else el
    for r in show:
        if r is None:
            print(f"  {'···':^82}")
            continue
        stored    = ts_to_str(r["ts"])
        submitted = ts_to_str(r["ts"] - tz * 3600)
        diff      = f" (−{tz}h)" if tz > 0 else (f" (+{abs(tz)}h)" if tz < 0 else "")
        print(f"  {r['artist'][:25]:<26} {r['track'][:27]:<28} {stored}  {submitted}{diff if tz else ''}")

    print(f"{'─'*84}")
    bad  = sum(1 for r in rows if r["bad_date"])
    skip = sum(1 for r in rows if r["rating"] == "S")
    print(f"  {len(el)} eligible  ·  {bad} bad-date excluded  ·  {skip} skipped excluded")
    if tz != 0:
        print(f"  TZ adjustment: UTC{tz:+d} → timestamps shifted by {-tz:+d}h before submit")
    print()

# ── Resource path ────────────────────────────────────────────────────────────
def get_editor_path() -> Path:
    try:
        from importlib.resources import files
        ref = files("bobbler").joinpath("bobbler_editor.html")
        p = Path(str(ref))
        if p.exists():
            return p
        import tempfile, shutil
        tmp = Path(tempfile.mktemp(suffix=".html"))
        with ref.open("rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return tmp
    except Exception:
        return Path(__file__).parent / "bobbler_editor.html"

# ── Native GUI Application ────────────────────────────────────────────────────
class ScrobbleApp(tk.Tk):
    def __init__(self, rows: list[dict], creds: dict, initial_tz: int, log_path: Path, keep_log: bool):
        super().__init__()
        self.title(f"Scrobble Log Editor - {log_path.name}")
        self.geometry("1100x700")
        self.rows = rows
        self.creds = creds
        self.log_path = log_path
        self.sort_col = "idx"
        self.sort_dir = False
        
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.style.configure("Treeview", rowheight=25)
        
        # Color mapping for runs
        self.run_colors = ["#f3e8ff", "#e0f2fe", "#dcfce7", "#ffedd5", "#fce7f3", "#fef9c3"]
        self.tag_colors = {
            "bad_date": "#fee2e2", "overlap": "#fef3c7", "edited": "#f0fdf4"
        }

        self.build_ui(initial_tz, keep_log)
        self.refresh_table()

    def build_ui(self, initial_tz, keep_log):
        # Top Toolbar
        top_frame = tk.Frame(self, padx=10, pady=10)
        top_frame.pack(fill=tk.X)
        
        self.lbl_stats = tk.Label(top_frame, font=("Helvetica", 10))
        self.lbl_stats.pack(side=tk.LEFT)
        
        tk.Label(top_frame, text="Search:").pack(side=tk.LEFT, padx=(20, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_table())
        tk.Entry(top_frame, textvariable=self.search_var, width=30).pack(side=tk.LEFT)

        # Batch Toolbar
        self.batch_frame = tk.Frame(self, bg="#f8fafc", padx=10, pady=5)
        
        tk.Button(self.batch_frame, text="⏱ Consecutive Plays...", command=self.batch_chain).pack(side=tk.LEFT, padx=5)
        tk.Button(self.batch_frame, text="🗑 Delete Selected", command=self.batch_delete, fg="red").pack(side=tk.LEFT, padx=5)

        # Treeview Setup
        tree_frame = tk.Frame(self, padx=10)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        scroll_y = ttk.Scrollbar(tree_frame)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        cols = ("idx", "artist", "album", "track", "num", "ts", "local", "dur", "rtg", "flags")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", yscrollcommand=scroll_y.set, selectmode="extended")
        scroll_y.config(command=self.tree.yview)
        
        headers = [("#", 40), ("Artist", 180), ("Album", 180), ("Track", 180), ("T#", 40), 
                   ("UTC", 140), ("Local", 140), ("Dur", 60), ("Rtg", 40), ("Flags", 80)]
        for col, (name, width) in zip(cols, headers):
            self.tree.heading(col, text=name, command=lambda c=col: self.sort_table(c))
            self.tree.column(col, width=width, anchor=tk.W if col in ("artist", "album", "track") else tk.CENTER)
            
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda e: self.edit_single())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_batch_toolbar())

        # Configure tags
        for tag, color in self.tag_colors.items():
            self.tree.tag_configure(tag, background=color)
        for i, color in enumerate(self.run_colors):
            self.tree.tag_configure(f"run_{i}", background=color)

        # Bottom Bar
        bottom = tk.Frame(self, padx=10, pady=10, bg="#1e293b")
        bottom.pack(fill=tk.X)
        
        tk.Label(bottom, text="Log TZ Offset:", bg="#1e293b", fg="white").pack(side=tk.LEFT)
        self.tz_var = tk.IntVar(value=initial_tz)
        ttk.Combobox(bottom, textvariable=self.tz_var, values=list(range(-12, 15)), width=4, state="readonly").pack(side=tk.LEFT, padx=5)
        self.tz_var.trace_add("write", lambda *args: self.refresh_table())
        
        tk.Button(bottom, text="⬆ Submit to Last.fm", command=self.submit_lfm, bg="#c084fc", fg="white").pack(side=tk.RIGHT, padx=10)
        tk.Button(bottom, text="💾 Save .log", command=self.save_log).pack(side=tk.RIGHT, padx=5)
        
        self.keep_var = tk.BooleanVar(value=keep_log)
        tk.Checkbutton(bottom, text="Keep .log file", variable=self.keep_var, bg="#1e293b", fg="white", selectcolor="#1e293b").pack(side=tk.RIGHT, padx=10)

    def sort_table(self, col):
        if self.sort_col == col:
            self.sort_dir = not self.sort_dir
        else:
            self.sort_col = col
            self.sort_dir = False
        self.refresh_table()

    def refresh_table(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        
        q = self.search_var.get().lower()
        display = []
        for r in self.rows:
            if not q or any(q in str(r[k]).lower() for k in ("artist", "album", "track")):
                display.append(r)
                
        def get_sort_val(r):
            v = r.get(self.sort_col, r.get("original_ts"))
            return v.lower() if isinstance(v, str) else (v or 0)
            
        display.sort(key=get_sort_val, reverse=self.sort_dir)
        
        tz_off = self.tz_var.get()
        bad, ovl, runs = 0, 0, set()
        
        for r in display:
            if r["bad_date"]: bad += 1
            if r["overlap"]: ovl += 1
            if r["run_id"] is not None: runs.add(r["run_id"])
            
            flags = []
            tags = ()
            if r["bad_date"]: flags.append("BAD"); tags = ("bad_date",)
            elif r["overlap"]: flags.append("OVL"); tags = ("overlap",)
            elif r["run_id"] is not None: flags.append("RUN"); tags = (f"run_{r['run_id'] % len(self.run_colors)}",)
            if r["edited"]: tags = ("edited",)

            self.tree.insert("", "end", iid=str(r["file_idx"]), values=(
                r["file_idx"]+1, r["artist"], r["album"], r["track"], r["num"],
                ts_to_str(r["ts"]), ts_to_str(r["ts"] + tz_off * 3600), fmt_dur(r["dur"]), r["rating"], ", ".join(flags)
            ), tags=tags)

        self.lbl_stats.config(text=f"{len(self.rows)} tracks | {bad} bad dates | {ovl} overlaps | {len(runs)} album runs")
        self.update_batch_toolbar()

    def update_batch_toolbar(self):
        if self.tree.selection():
            self.batch_frame.pack(fill=tk.X, before=self.tree.master)
        else:
            self.batch_frame.pack_forget()

    def get_selected_rows(self):
        return [next(r for r in self.rows if str(r["file_idx"]) == iid) for iid in self.tree.selection()]

    def batch_delete(self):
        sel = self.get_selected_rows()
        if messagebox.askyesno("Confirm Delete", f"Delete {len(sel)} entries?"):
            self.rows = [r for r in self.rows if r not in sel]
            self.rows = build_chains(self.rows)
            self.refresh_table()

    def batch_chain(self):
        sel = self.get_selected_rows()
        top = tk.Toplevel(self)
        top.title("Consecutive Plays")
        top.geometry("450x250")
        top.grab_set()

        tk.Label(top, text=f"Chain timestamps for {len(sel)} tracks:", font=("", 10, "bold")).pack(pady=10)
        tk.Label(top, text="Start Datetime (YYYY-MM-DD HH:MM:SS UTC):").pack()
        e_time = tk.Entry(top, width=30)
        e_time.pack(pady=5)
        
        tk.Label(top, text="Order by:").pack()
        order_var = tk.StringVar(value="fileline")
        tk.Radiobutton(top, text="File Order", variable=order_var, value="fileline").pack()
        tk.Radiobutton(top, text="Track Number", variable=order_var, value="tracknum").pack()

        def apply():
            try:
                dt = datetime.strptime(e_time.get().strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                cursor = int(dt.timestamp())
            except:
                messagebox.showerror("Error", "Invalid time format.", parent=top)
                return

            ordered = sorted(sel, key=lambda x: x["num"] if order_var.get() == "tracknum" else x["file_idx"])
            for r in ordered:
                r["ts"] = cursor
                r["edited"] = True
                cursor += r["dur"]

            self.rows = build_chains(self.rows)
            self.refresh_table()
            top.destroy()

        tk.Button(top, text="Apply Chain", command=apply, bg="#c084fc", fg="white").pack(pady=15)

    def edit_single(self):
        sel = self.tree.selection()
        if not sel: return
        r = next(row for row in self.rows if str(row["file_idx"]) == sel[0])

        top = tk.Toplevel(self)
        top.title("Edit Scrobble")
        top.geometry("400x320")
        top.grab_set()

        entries = {}
        for i, (label, key) in enumerate([("Artist", "artist"), ("Album", "album"), ("Track", "track")]):
            tk.Label(top, text=label).grid(row=i, column=0, sticky="e", padx=10, pady=5)
            e = tk.Entry(top, width=40)
            e.insert(0, r[key])
            e.grid(row=i, column=1, pady=5)
            entries[key] = e

        tk.Label(top, text="Time (UTC):").grid(row=3, column=0, sticky="e", padx=10, pady=5)
        e_time = tk.Entry(top, width=40)
        e_time.insert(0, ts_to_str(r["ts"]) if not r["bad_date"] else "")
        e_time.grid(row=3, column=1, pady=5)

        chain_var = tk.BooleanVar(value=False)
        chain_rows = [x for x in self.rows if x["run_id"] == r["run_id"]] if r["run_id"] is not None else []
        if len(chain_rows) > 1:
            tk.Checkbutton(top, text=f"Apply time chaining to full album run ({len(chain_rows)} tracks)", variable=chain_var).grid(row=4, column=0, columnspan=2, pady=10)

        def apply():
            try:
                dt = datetime.strptime(e_time.get().strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                new_ts = int(dt.timestamp())
            except:
                messagebox.showerror("Error", "Invalid time format.", parent=top)
                return

            if chain_var.get():
                cursor = new_ts
                for cr in sorted(chain_rows, key=lambda x: x["num"]):
                    cr["ts"] = cursor
                    cr["edited"] = True
                    cursor += cr["dur"]
            else:
                r["ts"] = new_ts
                r["artist"], r["album"], r["track"] = entries["artist"].get(), entries["album"].get(), entries["track"].get()
                r["edited"] = True

            self.rows = build_chains(self.rows)
            self.refresh_table()
            top.destroy()

        tk.Button(top, text="Save Changes", command=apply, bg="#4ade80").grid(row=5, column=0, columnspan=2, pady=15)

    def save_log(self):
        f = filedialog.asksaveasfilename(initialfile=".scrobbler.log", defaultextension=".log")
        if not f: return
        hdr = "#AUDIOSCROBBLER/1.1\n#TZ/UNKNOWN\n#CLIENT/Rockbox .scrobbler.log\n#ARTIST\t#ALBUM\t#TITLE\t#TRACKNUM\t#LENGTH\t#RATING\t#TIMESTAMP\t#MUSICBRAINZ_TRACKID\n"
        lines = [f"{r['artist']}\t{r['album']}\t{r['track']}\t{r['num']}\t{r['dur']}\t{r['rating']}\t{r['ts']}\t{r['mbid']}" for r in sorted(self.rows, key=lambda x: x["file_idx"])]
        with open(f, "w", encoding="utf-8") as out:
            out.write(hdr + "\n".join(lines) + "\n")
        messagebox.showinfo("Saved", f"Successfully saved {len(lines)} entries to {Path(f).name}.")

    def submit_lfm(self):
        el = eligible(self.rows)
        if not el:
            messagebox.showinfo("Nothing to submit", "No eligible scrobbles. Fix bad dates first.")
            return
        
        tz_off = self.tz_var.get()
        if not messagebox.askyesno("Confirm Submit", f"Submit {len(el)} scrobbles to Last.fm as {self.creds['username']}?\n\nTimezone offset applied before submit: UTC{'+' if tz_off>0 else ''}{tz_off}"):
            return

        prog = tk.Toplevel(self)
        prog.title("Submitting...")
        prog.geometry("300x100")
        prog.grab_set()
        lbl = tk.Label(prog, text="Authenticating...", pady=20)
        lbl.pack()
        self.update()

        try: sk = lfm_get_session(self.creds)
        except Exception as e: prog.destroy(); messagebox.showerror("Auth Failed", str(e)); return

        BATCH, ok, fail, errs = 50, 0, 0, []
        for i in range(0, len(el), BATCH):
            lbl.config(text=f"Submitting {min(i+BATCH, len(el))}/{len(el)}...")
            self.update()
            batch = el[i:i+BATCH]
            try:
                a, f, e = lfm_submit_batch(batch, self.creds, sk, tz_off)
                ok += a; fail += f; errs.extend(e)
            except Exception as ex:
                fail += len(batch)
                errs.append(f"Batch failed: {ex}")

        prog.destroy()
        res = f"{ok} accepted, {fail} rejected."
        if errs: res += "\n\nIssues:\n" + "\n".join(errs[:10]) + (f"\n...and {len(errs)-10} more." if len(errs)>10 else "")
        
        if ok > 0 and not self.keep_var.get():
            try:
                os.remove(self.log_path)
                res += f"\n\nDeleted {self.log_path.name}."
            except OSError as e:
                res += f"\n\nCould not delete {self.log_path.name}: {e}"
                
        messagebox.showinfo("Complete", res)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(prog="bobbler", description="iPod .scrobbler.log → Last.fm submission tool")
    parser.add_argument("-p", "--path", metavar="FILE", help="Path to .scrobbler.log")
    parser.add_argument("-e", "--edit", action="store_true", help="Open the GUI editor instead of submitting immediately")
    parser.add_argument("--tz", type=int, default=None, metavar="OFFSET", help="Timezone offset (e.g. 8 = UTC+8)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be submitted, don't send")
    parser.add_argument("--username", default=None, help="Override saved Last.fm username")
    parser.add_argument("--password", default=None, help="Override saved Last.fm password")
    parser.add_argument("--save-creds", action="store_true", help="Save credentials and exit")
    parser.add_argument("--keep", action="store_true", help="Do not delete the .scrobbler.log file after submitting (default: delete)")
    args = parser.parse_args()

    if args.save_creds:
        save_creds_interactive()
        return

    cfg = load_config()
    if not CONFIG_PATH.exists() or "lastfm" not in cfg or not cfg["lastfm"].get("username"):
        cfg = prompt_and_save_creds(cfg)

    tz = args.tz if args.tz is not None else int(cfg["lastfm"].get("tz_offset", 0) if "lastfm" in cfg else 0)
    log = resolve_log(args)
    creds = get_creds(args, cfg)
    rows = parse_log(log)

    if args.edit:
        app = ScrobbleApp(rows, creds, tz, log, args.keep)
        app.mainloop()
        return

    el = eligible(rows)
    print(f"\n  File     : {log}")
    print(f"  Entries  : {len(rows)} total  ·  {sum(1 for r in rows if r['bad_date'])} bad-date")
    print(f"  Eligible : {len(el)}\n  TZ offset: UTC{tz:+d}")

    if not el: return print("\nNothing to submit.")

    if args.dry_run:
        print_preview(rows, tz)
        return print("Dry run — nothing submitted.")

    try:
        if input(f"Submit {len(el)} scrobbles to Last.fm? [y/N] ").strip().lower() != "y": return
    except: return

    try: sk = lfm_get_session(creds)
    except Exception as e: return print(f"Auth failed: {e}")

    ok, fail = 0, 0
    for i in range(0, len(el), 50):
        a, f, errs = lfm_submit_batch(el[i:i+50], creds, sk, tz)
        ok += a; fail += f
        print(f"\r  Submitted {min(i+50, len(el))}/{len(el)}...", end="", flush=True)
    print(f"\n{ok} accepted, {fail} rejected.")
    
    if ok > 0 and not args.keep:
        try:
            os.remove(log)
            print(f"Deleted {log.name}.")
        except OSError as e:
            print(f"Could not delete {log.name}: {e}")

if __name__ == "__main__":
    main()
def cli():
    main()
