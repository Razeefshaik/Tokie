"""Tokie - a tiny always-on-top desktop pet that eats your Claude + Codex tokens.

Three sizes: mini square icon -> click it for the counter card with the cat -> "Show details" for charts
and tables. Drag it anywhere, right-click for the menu, power button turns it off.
Data layer lives in tokie_data.py.
Run:  pythonw tokie.py   (or the packaged Tokie.exe)
"""
import ctypes
import json
import math
import os
import random
import sys
import threading
import tkinter as tk
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk

import tokie_data as tu

KEY = "#010203"  # window colour made transparent, so the card can have round corners
BG, PANEL, LINE = "#161823", "#1f2332", "#2d3249"
FG, MUTED = "#eceefb", "#8b91ab"
CLAUDE, CODEX, ACCENT = "#ff9b71", "#6aa5ff", "#8f7bff"
PAD = 12
PET = 96  # pet canvas size (counter card)
MINI = 40  # icon size in the mini square
REFRESH_MS = 120_000
STATE_FILE = tu.DATA_DIR / "tokie_state.json"
ICON = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "tokie.ico"  # _MEIPASS = PyInstaller
MOODS = {  # body colour per mood
    "sleepy": "#9aa5d6", "calm": "#7ee0c3", "happy": "#ffd77a", "stuffed": "#ff9b8f",
}
QUIPS = ["Hehe!", "Nom nom?", "Feed me tokens!", "Boop!", "I can count to a billion.",
         "Cache reads taste best.", "Still hungry...", "Wheee!"]


def round_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def pill(parent, text, cmd, bg=PANEL, fg=FG, hover=LINE, font=("Segoe UI", 9), padx=10, pady=3):
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2")
    lbl._nodrag = True
    lbl.bind("<Button-1>", lambda _e: cmd())
    lbl.bind("<Enter>", lambda _e: lbl.config(bg=hover))
    lbl.bind("<Leave>", lambda _e: lbl.config(bg=bg))
    return lbl


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Tokie(tk.Tk):
    COLS = ("input", "output", "cache_write", "cache_read")

    def __init__(self):
        super().__init__()
        self.state_ = load_state()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=KEY)
        self.attributes("-transparentcolor", KEY)
        self.title("Tokie")
        try:
            self.iconbitmap(default=str(ICON))
        except tk.TclError:  # icon file missing: keep Tk's default
            pass

        self.agent = tk.StringVar(value="All")
        self.cache = tk.BooleanVar(value=True)
        self.ontop = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Loadingâ€¦")
        self.records, self.parts = [], None
        self.prev_total = None
        self.mode = "mini"  # mini square icon -> card (with the cat) -> details
        self.busy = False
        self.tick = self.hop = self.eat = 0
        self.eat_text = ""
        self.mood_name = "sleepy"
        self.speech_override = ("", 0.0)

        self._style()
        self.bgc = tk.Canvas(self, bg=KEY, highlightthickness=0)
        self.bgc.pack(fill="both", expand=True)
        self.body = tk.Frame(self.bgc, bg=BG)
        self.bgc.create_window(PAD, PAD, window=self.body, anchor="nw", tags="body")
        self.bgc.bind("<Configure>", self._paint_card)

        self._build_header()
        self.details = tk.Frame(self.body, bg=BG)
        self._build_details()

        self.make_draggable(self.bgc)
        self.make_draggable(self.header)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Refresh", command=self.refresh)
        self.menu.add_command(label="Mini icon", command=lambda: self.set_mode("mini"))
        self.menu.add_command(label="Counter", command=lambda: self.set_mode("card"))
        self.menu.add_command(label="Details", command=lambda: self.set_mode("details"))
        self.menu.add_checkbutton(label="Always on top", variable=self.ontop,
                                  command=lambda: self.attributes("-topmost", self.ontop.get()))
        self.menu.add_separator()
        self.menu.add_command(label="Turn off Tokie", command=self.quit_app)
        for w in (self.bgc, self.header, self.pet, self.mini):
            w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

        self.set_mode("mini", initial=True)
        self.animate()
        self.refresh()

    # ---------- styling ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=LINE)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED)
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(12, 5), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", LINE)], foreground=[("selected", FG)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24,
                    borderwidth=0)
        s.configure("Treeview.Heading", background=LINE, foreground=MUTED, relief="flat", padding=(6, 4))
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        s.map("Treeview.Heading", background=[("active", LINE)])
        s.configure("Vertical.TScrollbar", background=LINE, troughcolor=PANEL, bordercolor=PANEL,
                    arrowcolor=MUTED, relief="flat")

    def _paint_card(self, _e=None):
        w, h = self.bgc.winfo_width(), self.bgc.winfo_height()
        self.bgc.delete("card")
        if self.mode == "mini":
            round_rect(self.bgc, 2, 2, w - 2, h - 2, 16, fill=BG, outline=LINE, tags="card")
        else:
            round_rect(self.bgc, 2, 2, w - 2, h - 2, 26, fill=BG, outline=LINE, tags="card")
        self.bgc.tag_lower("card")

    # ---------- compact header ----------
    def _build_header(self):
        self.header = tk.Frame(self.body, bg=BG)
        self.header.pack(fill="x")
        self.pet = tk.Canvas(self.header, width=PET, height=PET, bg=BG, highlightthickness=0, cursor="hand2")
        self.pet.grid(row=0, column=0, rowspan=2, sticky="n")
        self.pet.bind("<ButtonRelease-1>", self._pet_click)
        self.mini = tk.Canvas(self.header, width=MINI, height=MINI, bg=BG, highlightthickness=0, cursor="hand2")
        self.mini.grid(row=0, column=0)
        self.mini.grid_remove()
        self.mini.bind("<ButtonRelease-1>", self._mini_click)

        mid = self.mid = tk.Frame(self.header, bg=BG)
        mid.grid(row=0, column=1, sticky="w", padx=(6, 10))
        self.lbl_title = tk.Label(mid, text="TOKENS Â· ALL", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"))
        self.lbl_title.pack(anchor="w")
        self.lbl_big = tk.Label(mid, text="â€“", bg=BG, fg=FG, font=("Segoe UI", 24, "bold"))
        self.lbl_big.pack(anchor="w")
        self.lbl_speech = tk.Label(mid, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), width=24, anchor="w")
        self.lbl_speech.pack(anchor="w")

        btns = self.btns = tk.Frame(self.header, bg=BG)
        btns.grid(row=0, column=2, sticky="ne")
        btns._nodrag = True
        pill(btns, "â†»", self.refresh, bg=BG, padx=6).pack(side="left")
        pill(btns, "â€“", lambda: self.set_mode("mini"), bg=BG, padx=6).pack(side="left")  # shrink to the mini icon

        # Bottom row: the power button sits bottom-left, far from "â€“" (top-right), so it isn't hit by mistake.
        self.bottom = tk.Frame(self.header, bg=BG)
        self.bottom.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.bottom._nodrag = True
        pill(self.bottom, "â»  Turn off", self.quit_app, fg="#ff8f8f", hover="#5a2b35").pack(side="left", fill="y")
        self.btn_toggle = pill(self.bottom, "Show details  â–¾", self.toggle)
        self.btn_toggle.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.header.columnconfigure(1, weight=1)

    # ---------- details ----------
    def _build_details(self):
        d = self.details
        top = tk.Frame(d, bg=BG)
        top.pack(fill="x", pady=(10, 6))
        self.seg = {}
        for name in ("All", "Codex", "Claude"):
            lbl = tk.Label(top, text=name, font=("Segoe UI", 9, "bold"), padx=14, pady=4, cursor="hand2")
            lbl.pack(side="left", padx=(0, 4))
            lbl.bind("<Button-1>", lambda _e, n=name: self.set_agent(n))
            self.seg[name] = lbl
        tk.Checkbutton(top, text="include cache reads", variable=self.cache, command=self.render, bg=BG, fg=MUTED,
                       selectcolor=PANEL, activebackground=BG, activeforeground=FG, highlightthickness=0,
                       bd=0, font=("Segoe UI", 9)).pack(side="left", padx=10)

        row = tk.Frame(d, bg=BG)
        row.pack(fill="x")
        self.cards = {}
        for name in ("Today", "Last 7 days", "Last 30 days", "Lifetime"):
            f = tk.Frame(row, bg=PANEL, padx=12, pady=8)
            f.pack(side="left", expand=True, fill="x", padx=(0, 6))
            tk.Label(f, text=name.upper(), bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
            big = tk.Label(f, text="â€“", bg=PANEL, fg=FG, font=("Segoe UI", 16, "bold"))
            big.pack(anchor="w")
            sub = tk.Label(f, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
            sub.pack(anchor="w")
            self.cards[name] = (big, sub)

        self.chart = tk.Canvas(d, width=660, height=120, bg=PANEL, highlightthickness=0)
        self.chart.pack(fill="x", pady=(8, 4))
        self.chart.bind("<Configure>", lambda _e: self.draw_chart())

        self.tabs = ttk.Notebook(d)
        self.tabs.pack(fill="both", expand=True)
        self.trees = {}
        for key, title, first in (("daily", "Daily", "Date"), ("source", "Source", "Source"),
                                  ("model", "Models", "Model")):
            fr = ttk.Frame(self.tabs)
            self.tabs.add(fr, text=title)
            cols = ("name", "agent", "input", "output", "cache_write", "cache_read", "total")
            tv = ttk.Treeview(fr, columns=cols, show="headings", height=5)
            for c, h in zip(cols, (first, "Agent", "Input", "Output", "Cache write", "Cache read", "Total")):
                tv.heading(c, text=h)
                tv.column(c, width=150 if c == "name" else 100 if c.startswith("cache") else 88,
                          anchor="w" if c in ("name", "agent") else "e")
            sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=sb.set)
            tv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.trees[key] = tv
        self._build_profiles_tab()
        ttk.Label(d, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    def _build_profiles_tab(self):
        fr = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(fr, text="Codex accounts")
        self.prof_summary = ttk.Label(fr, font=("Segoe UI", 10, "bold"))
        self.prof_summary.pack(anchor="w")
        cols = ("handle", "lifetime", "peak", "task", "longest", "current", "local")
        self.prof_tree = ttk.Treeview(fr, columns=cols, show="headings", height=3)
        for c, h, w in (("handle", "Profile", 170), ("lifetime", "Lifetime", 80), ("peak", "Peak", 70),
                        ("task", "Longest task", 90), ("longest", "Best streak", 80),
                        ("current", "Streak", 70), ("local", "Log ID", 80)):
            self.prof_tree.heading(c, text=h)
            self.prof_tree.column(c, width=w, anchor="w" if c in ("handle", "local") else "e")
        self.prof_tree.pack(fill="x", pady=(4, 6))
        ttk.Label(fr, text="Local logs on this PC, per Codex account ID", style="Muted.TLabel").pack(anchor="w")
        lcols = ("id", "total", "nocache", "first", "last", "profile")
        self.loc_tree = ttk.Treeview(fr, columns=lcols, show="headings", height=2)
        for c, h, w in (("id", "Account ID", 90), ("total", "Total", 110), ("nocache", "Excl. cache", 110),
                        ("first", "First day", 90), ("last", "Last day", 90), ("profile", "Matched profile", 150)):
            self.loc_tree.heading(c, text=h)
            self.loc_tree.column(c, width=w, anchor="w" if c in ("id", "profile") else "e")
        self.loc_tree.pack(fill="x", pady=(4, 4))
        self.prof_note = ttk.Label(fr, style="Muted.TLabel", wraplength=620, justify="left")
        self.prof_note.pack(anchor="w")
        pill(fr, "Edit profiles file", lambda: os.startfile(tu.PROFILES_FILE)).pack(anchor="w", pady=(4, 0))

    # ---------- window behaviour ----------
    def make_draggable(self, w):
        if getattr(w, "_nodrag", False):
            return
        w.bind("<ButtonPress-1>", self._drag_start, add="+")
        w.bind("<B1-Motion>", self._drag_move, add="+")
        w.bind("<ButtonRelease-1>", self._drag_end, add="+")
        for ch in w.winfo_children():
            self.make_draggable(ch)

    def _drag_start(self, e):
        self._dx, self._dy, self._moved = e.x_root - self.winfo_x(), e.y_root - self.winfo_y(), False

    def _drag_move(self, e):
        self._moved = True
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _drag_end(self, _e):
        if getattr(self, "_moved", False):
            self.save_state()

    def fit(self, initial=False):
        self.update_idletasks()
        w, h = self.body.winfo_reqwidth() + 2 * PAD, self.body.winfo_reqheight() + 2 * PAD
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if initial:
            x = self.state_.get("x", sw - w - 40)
            y = self.state_.get("y", sh - h - 120)
        else:
            x, y = self.winfo_x(), self.winfo_y()
            if self.winfo_width() > 1:  # keep the pet's right edge where it was when the window grows/shrinks
                x += self.winfo_width() - w
        x, y = max(0, min(x, sw - w)), max(0, min(y, sh - h - 50))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._paint_card()

    def set_mode(self, mode, initial=False):
        """mini = small square icon, card = cat + counter, details = counter + charts/tables."""
        self.mode = mode
        for w in (self.pet, self.mid, self.btns, self.bottom):
            if mode == "mini":
                w.grid_remove()
            else:
                w.grid()
        if mode == "mini":
            self.mini.grid()
        else:
            self.mini.grid_remove()
        if mode == "details":
            self.details.pack(fill="x")
            self.btn_toggle.config(text="Hide details  â–´")
        else:
            self.details.pack_forget()
            self.btn_toggle.config(text="Show details  â–¾")
        self.fit(initial=initial)
        self.render()
        if not initial:
            self.save_state()

    def toggle(self):
        self.set_mode("card" if self.mode == "details" else "details")

    def set_agent(self, name):
        self.agent.set(name)
        self.render()

    def save_state(self):
        try:
            STATE_FILE.write_text(json.dumps({"x": self.winfo_x(), "y": self.winfo_y()}), encoding="utf-8")
        except OSError:
            pass

    def quit_app(self):
        self.save_state()
        self.destroy()

    # ---------- the pet ----------
    def _pet_click(self, _e):
        if getattr(self, "_moved", False):
            return
        self.hop = 14
        self.speech_override = (random.choice(QUIPS), datetime.now().timestamp() + 3)
        self._set_speech()

    def _mini_click(self, _e):
        if not getattr(self, "_moved", False):
            self.set_mode("card")

    TICK = 40  # ms per animation frame; t-based effects below were tuned for 70 ms steps

    def animate(self):
        step = self.TICK / 70
        self.tick += 1
        self.hop = max(0, self.hop - step)
        self.eat = max(0, self.eat - step)
        if self.mode == "mini":
            self.draw_mini()
        else:
            self.draw_pet()
        self.after(self.TICK, self.animate)

    def draw_mini(self):
        """Simple icon for the mini square: three token bars that bounce a little when new tokens arrive."""
        c = self.mini
        t = self.tick * self.TICK / 70
        c.delete("all")
        base, w, gap = MINI - 8, 7, 4
        x0 = (MINI - (3 * w + 2 * gap)) / 2
        for i, (h, color) in enumerate(((12, CLAUDE), (22, ACCENT), (16, CODEX))):
            if self.eat:
                h += abs(math.sin(t / 2 + i)) * 6
            x = x0 + i * (w + gap)
            round_rect(c, x, base - h, x + w, base, 3, fill=color, outline="")
        if self.mood_name == "sleepy":
            c.create_text(MINI - 6, 7, text="z", fill=MUTED, font=("Segoe UI", 7, "bold"))

    def draw_pet(self):
        c, mood = self.pet, self.mood_name
        t = self.tick * self.TICK / 70
        c.delete("all")
        bob = math.sin(t / 7) * 2 - (abs(math.sin(self.hop / 4.5)) * 12 if self.hop else 0)
        cx = PET / 2
        dark = "#2b2438"
        puff = 5 if mood == "stuffed" else 0
        col = MOODS[mood]
        cy = PET / 2 + 6 + bob
        c.create_oval(cx - 24, PET - 12, cx + 24, PET - 3, fill="#10121a", outline="")
        c.create_polygon(cx - 25, cy - 12, cx - 19, cy - 33, cx - 7, cy - 20, fill=col, outline="")
        c.create_polygon(cx + 25, cy - 12, cx + 19, cy - 33, cx + 7, cy - 20, fill=col, outline="")
        c.create_oval(cx - 27 - puff, cy - 22 - puff / 2, cx + 27 + puff, cy + 21 + puff / 2, fill=col, outline="")
        c.create_oval(cx - 22, cy + 2, cx - 14, cy + 8, fill="#ff8fa3", outline="", stipple="gray50")
        c.create_oval(cx + 14, cy + 2, cx + 22, cy + 8, fill="#ff8fa3", outline="", stipple="gray50")
        blink = (t % 64) < 3
        for sx in (-11, 11):
            x, y = cx + sx, cy - 4
            if mood == "sleepy" or blink:
                c.create_line(x - 5, y, x + 5, y, fill=dark, width=2, capstyle="round")
            elif mood == "happy" or self.eat:
                c.create_arc(x - 5, y - 4, x + 5, y + 6, start=0, extent=180, style="arc", outline=dark, width=2)
            elif mood == "stuffed":
                d = -1 if sx < 0 else 1
                c.create_line(x - 4 * d, y - 4, x + 3 * d, y, x - 4 * d, y + 4, fill=dark, width=2, capstyle="round")
            else:
                c.create_oval(x - 3, y - 4, x + 3, y + 4, fill=dark, outline="")
                c.create_oval(x - 1, y - 3, x + 1, y - 1, fill="#ffffff", outline="")
        my = cy + 8
        if self.eat:
            r = 3 + abs(math.sin(t / 2)) * 4
            c.create_oval(cx - r, my - r / 2, cx + r, my + r, fill=dark, outline="")
        elif mood == "stuffed":
            c.create_oval(cx - 3, my - 1, cx + 3, my + 5, fill=dark, outline="")
        elif mood == "sleepy":
            c.create_oval(cx - 2, my, cx + 2, my + 3, fill=dark, outline="")
        else:
            c.create_arc(cx - 6, my - 5, cx + 6, my + 5, start=200, extent=140, style="arc", outline=dark, width=2)
        self._draw_extras(c, t, mood, cx, cy)

    def _draw_extras(self, c, t, mood, cx, cy):
        """Mood decorations around the pet: Zzz, sparkles, sweat drop, and the floating +N when it eats."""
        if mood == "sleepy":
            for i, (z, dx) in enumerate((("z", 0), ("Z", 9))):
                c.create_text(cx + 24 + dx, cy - 26 - i * 9 - (t // 6 + i * 3) % 7, text=z, fill=MUTED,
                              font=("Segoe UI", 8 + i * 3, "bold"))
        elif mood == "happy" and (t // 10) % 2:
            c.create_text(cx + 30, cy - 24, text="âœ¦", fill="#ffe9a8", font=("Segoe UI", 10))
        elif mood == "stuffed":
            c.create_oval(cx + 26, cy - 22, cx + 31, cy - 14, fill="#7fd0ff", outline="")
        if self.eat:
            c.create_text(cx + 6, 18 - (28 - self.eat) * 0.25, text=self.eat_text, fill=CODEX,
                          font=("Segoe UI", 9, "bold"))

    def pick_mood(self):
        today = datetime.now().strftime("%Y-%m-%d")
        per = defaultdict(int)
        for r in self.records:
            per[r["date"]] += tu.rec_total(r)
        t = per.get(today, 0)
        prev = [per[d] for d in sorted(per) if d < today][-14:]
        avg = sum(prev) / len(prev) if prev else 0
        if t == 0:
            return "sleepy", t
        if avg and t > 1.5 * avg:
            return "stuffed", t
        if avg and t < 0.5 * avg:
            return "calm", t
        return "happy", t

    # ---------- data ----------
    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.status.set("Scanning logsâ€¦")
        result = {}

        def work():
            c, nc = tu.load_claude()
            x, nx = tu.load_codex()
            result["v"] = (c + x, nc, nx)  # Tk calls stay on the main thread: poll for this

        def poll():
            if "v" in result:
                self.busy = False
                self.loaded(*result["v"])
            else:
                self.after(100, poll)
        threading.Thread(target=work, daemon=True).start()
        self.after(100, poll)

    def loaded(self, recs, nc, nx):
        self.records = recs
        if getattr(self, "_timer", None):
            self.after_cancel(self._timer)
        self._timer = self.after(REFRESH_MS, self.refresh)  # one rolling auto-refresh
        data = tu.load_profiles()
        changed = tu.ensure_combined(data, recs)
        self.parts, added = tu.compute_combined(data, recs)
        if changed or added != data["combined"]["ledger"]:
            data["combined"]["ledger"] = added
            tu.save_profiles(data)
        total = self.parts["total"]
        if self.prev_total is not None and total > self.prev_total:
            self.eat, self.eat_text = 28, f"+{tu.short(total - self.prev_total)}"
        self.prev_total = total
        self.status.set(f"{len(recs):,} records from {nc} Claude + {nx} Codex logs Â· "
                        f"updated {datetime.now():%H:%M:%S}")
        self.render()

    def total(self, r):
        t = r["input"] + r["output"] + r["cache_write"]
        return t + r["cache_read"] if self.cache.get() else t

    def filtered(self):
        a = self.agent.get()
        return [r for r in self.records if a == "All" or r["agent"] == a]

    def lifetime(self):
        p, a = self.parts, self.agent.get()
        return {"Codex": p["codex_base"] + p["codex_added"], "Claude": p["claude_base"] + p["claude_added"],
                "All": p["total"]}[a]

    def render(self):
        if not self.parts:
            return
        self.mood_name, today_tot = self.pick_mood()
        agent = self.agent.get()
        self.lbl_title.config(text=f"TOKENS Â· {agent.upper()}")
        self.lbl_big.config(text=tu.short(self.lifetime()))
        said = {"sleepy": "Zzzâ€¦ nothing eaten today", "calm": f"Nibbling Â· {tu.short(today_tot)} today",
                "happy": f"Yum! {tu.short(today_tot)} today", "stuffed": f"So full! {tu.short(today_tot)} today"}
        self.speech_text = said[self.mood_name]
        self._set_speech()
        if self.mode != "details":
            return
        for name, lbl in self.seg.items():
            on = name == agent
            lbl.config(bg=ACCENT if on else PANEL, fg="#ffffff" if on else MUTED)
        recs = self.filtered()
        today = datetime.now().date()
        for name, days in (("Today", 0), ("Last 7 days", 6), ("Last 30 days", 29), ("Lifetime", None)):
            cutoff = None if days is None else (today - timedelta(days=days)).strftime("%Y-%m-%d")
            sel = [r for r in recs if cutoff is None or r["date"] >= cutoff]
            tot = self.lifetime() if days is None else sum(self.total(r) for r in sel)
            out = sum(r["output"] for r in sel)
            big, sub = self.cards[name]
            big.config(text=tu.short(tot))
            sub.config(text=f"{tu.fmt(tot)} Â· out {tu.short(out)}")
        self.fill("daily", recs, lambda r: (r["date"], r["agent"]), reverse=True)
        self.fill("source", recs, lambda r: (f'{r["source"]} Â· {r["account"]}' if r["agent"] == "Codex"
                                             else r["source"], r["agent"]))
        self.fill("model", recs, lambda r: (r["model"], r["agent"]))
        self.draw_chart()
        self.render_profiles()

    def _set_speech(self):
        text, until = self.speech_override
        if text and datetime.now().timestamp() < until:
            self.lbl_speech.config(text=text, fg=ACCENT)
            self.after(int(until * 1000 - datetime.now().timestamp() * 1000) + 50, self._set_speech)
        else:
            self.lbl_speech.config(text=getattr(self, "speech_text", ""), fg=MUTED)

    def fill(self, key, recs, keyfn, reverse=False):
        agg = defaultdict(lambda: dict.fromkeys(self.COLS, 0))
        for r in recs:
            a = agg[keyfn(r)]
            for c in self.COLS:
                a[c] += r[c]

        def tot(a):
            t = a["input"] + a["output"] + a["cache_write"]
            return t + a["cache_read"] if self.cache.get() else t
        tv = self.trees[key]
        tv.delete(*tv.get_children())
        items = sorted(agg.items(), key=(lambda kv: kv[0]) if reverse else (lambda kv: -tot(kv[1])),
                       reverse=reverse)
        for (name, agent), a in items:
            tv.insert("", "end", values=(name, agent, tu.fmt(a["input"]), tu.fmt(a["output"]),
                                         tu.fmt(a["cache_write"]), tu.fmt(a["cache_read"]), tu.fmt(tot(a))))

    def draw_chart(self):
        c = self.chart
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50:
            return
        days = [(datetime.now().date() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
        per = {d: {"Claude": 0, "Codex": 0} for d in days}
        for r in self.filtered():
            if r["date"] in per:
                per[r["date"]][r["agent"]] += self.total(r)
        peak = max((sum(v.values()) for v in per.values()), default=0) or 1
        left, bottom, top = 62, 22, 32
        bw = (w - left - 14) / len(days)
        c.create_text(10, 12, text="Last 30 days", anchor="w", fill=MUTED, font=("Segoe UI", 8, "bold"))
        c.create_text(left - 6, top, text=tu.short(peak), anchor="e", fill=MUTED, font=("Segoe UI", 8))
        c.create_line(left, h - bottom, w - 8, h - bottom, fill=LINE)
        c.create_line(left, top, w - 8, top, fill=LINE, dash=(2, 4))
        for i, d in enumerate(days):
            x0, y = left + i * bw + 2, h - bottom
            for agent, color in (("Claude", CLAUDE), ("Codex", CODEX)):
                v = per[d][agent]
                if v:
                    seg = max(2, (h - bottom - top) * v / peak)
                    c.create_rectangle(x0, y - seg, x0 + bw - 5, y, fill=color, outline="")
                    y -= seg
            if i % 6 == 0 or i == len(days) - 1:
                c.create_text(x0, h - 9, text=d[5:], anchor="w", fill=MUTED, font=("Segoe UI", 8))
        for x, name, color in ((w - 130, "Claude", CLAUDE), (w - 66, "Codex", CODEX)):
            c.create_oval(x, 8, x + 8, 16, fill=color, outline="")
            c.create_text(x + 12, 12, text=name, anchor="w", fill=FG, font=("Segoe UI", 8))

    def render_profiles(self):
        data = tu.load_profiles()
        profiles = data["profiles"]
        link = {p["local_id"]: p["handle"] for p in profiles if p.get("local_id")}
        self.prof_tree.delete(*self.prof_tree.get_children())
        for p in profiles:
            self.prof_tree.insert("", "end", values=(
                p["handle"], f'{p["lifetime_m"]:,.1f}M', f'{p["peak_m"]:,.1f}M', p["longest_task"],
                f'{p["longest_streak"]}d', f'{p["current_streak"]}d', p.get("local_id") or "-"))
        total_m = sum(p["lifetime_m"] for p in profiles)
        self.prof_summary.config(text=f"Profiles total: {total_m:,.1f}M tokens (as of {data.get('as_of', '?')})")
        loc = defaultdict(lambda: dict(total=0, cache=0, days=[]))
        for r in self.records:
            if r["agent"] == "Codex":
                a = loc[r["account"]]
                a["total"] += tu.rec_total(r)
                a["cache"] += r["cache_read"]
                a["days"].append(r["date"])
        self.loc_tree.delete(*self.loc_tree.get_children())
        local_sum = 0
        for acc, a in sorted(loc.items(), key=lambda kv: -kv[1]["total"]):
            local_sum += a["total"]
            self.loc_tree.insert("", "end", values=(acc, tu.fmt(a["total"]), tu.fmt(a["total"] - a["cache"]),
                                                    min(a["days"]), max(a["days"]), link.get(acc, "(not matched)")))
        self.prof_note.config(text=(
            f"Local logs: {tu.short(local_sum)} vs {total_m:,.1f}M on profiles. Profile total is the fixed start; "
            "only newer Codex usage is added. Set \"local_id\" in the profiles file to match a log ID."))


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # crisp text instead of Windows bitmap scaling
    except (AttributeError, OSError):
        pass
    Tokie().mainloop()
