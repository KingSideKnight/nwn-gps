"""GPS overlay on top of the game window (windowed or borderless mode).

  python -m nwngps.overlay "<destination>"     e.g. "vineyard", "city gates"
  python -m nwngps.overlay                     no destination: minimap only

Click-through and always on top; follows the game window, hides when the game
is minimised. Close with Ctrl+C in the terminal that started it.
Read-only towards the game; reads the database the recorder writes.
"""
import ctypes
import ctypes.wintypes as wt
import math
import queue
import signal
import sys
import threading
import time
import tkinter as tk

from .db import Store
from .nav import Navigator, compass
from .session import IN_GAME, Session

W, H = 320, 470
MAP_Y, MAP_SIZE = 150, 300
BG, FG, DIM = "#101418", "#e8eef2", "#7d8a94"
ACCENT, PIN, DOOR, ME, ROUTE = "#3fc1ff", "#f2c94c", "#b07a4a", "#3fc1ff", "#4cd964"

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetParent.restype = wt.HWND
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def game_client_rect(pid):
    """Screen rect (l, t, r, b) of the game's main window client area, or None if minimised/absent."""
    best = []

    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            r = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            best.append(((r.right - r.left) * (r.bottom - r.top), hwnd, r))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    if not best:
        return None
    _, hwnd, r = max(best, key=lambda b: b[0])
    if user32.IsIconic(hwnd) or r.right == 0:
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)


class Poller(threading.Thread):
    """Reads the game in the background so the UI never blocks (table locates take seconds)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue(maxsize=1)
        self.session = Session(log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
        self.pid = None

    def run(self):
        while True:
            snap = self.session.poll()
            self.pid = self.session.mem.pid if self.session.mem else None
            if self.q.full():
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    pass
            self.q.put(snap)
            time.sleep(0.15)


class Overlay:
    def __init__(self, dest_text):
        self.store = Store()
        self.nav = None
        if dest_text:
            hits = self.store.search(dest_text)
            if not hits:
                sys.exit(f"nothing in the database matches {dest_text!r}")
            self.nav = Navigator(self.store, hits[0])
            print(f"navigating to {hits[0]['name']} in {self.store.area_name(hits[0]['area'])}")
        self.poller = Poller()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.geometry(f"{W}x{H}+40+40")
        self.c = tk.Canvas(self.root, width=W, height=H, bg=BG, highlightthickness=0)
        self.c.pack()
        self.snap, self.area_pois, self.pois_area = None, [], None
        self.root.after(100, self._make_click_through)
        signal.signal(signal.SIGINT, lambda *a: self.root.after(0, self.root.destroy))

    def _make_click_through(self):
        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                 ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.root.attributes("-alpha", 0.86)

    # --- loop -----------------------------------------------------------------
    def tick(self):
        try:
            self.snap = self.poller.q.get_nowait()
        except queue.Empty:
            pass
        self._follow_game()
        self.draw()
        self.root.after(100, self.tick)

    def _follow_game(self):
        rect = game_client_rect(self.poller.pid) if self.poller.pid else None
        if rect is None:
            if self.root.state() != "withdrawn" and self.poller.pid:
                self.root.withdraw()
            return
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self._make_click_through()
        l, t, r, b = rect
        self.root.geometry(f"+{r - W - 16}+{t + 16}")

    def run(self):
        self.poller.start()
        self.root.after(100, self.tick)
        try:
            self.root.mainloop()
        finally:
            self.store.close()

    # --- drawing --------------------------------------------------------------
    def draw(self):
        c, s = self.c, self.snap
        c.delete("all")
        g = self.nav.update(s) if (self.nav and s) else None
        title = g.dest_name if g else "GPS"
        c.create_text(14, 14, anchor="nw", text=title[:38], fill=FG, font=("Segoe UI", 11, "bold"))
        if not s or s.state != IN_GAME:
            msg = {"NO_GAME": "Waiting for the game...", "MENU": "In menus", "LOADING": "Loading..."}.get(
                s.state if s else "", "Starting...")
            c.create_text(W / 2, 90, text=msg, fill=DIM, font=("Segoe UI", 12))
            return
        if g:
            self._draw_guidance(g)
        else:
            c.create_text(14, 40, anchor="nw", text="No destination set", fill=DIM, font=("Segoe UI", 10))
        self._draw_map(s, g)
        footer = f"{s.area_name or s.area}"
        c.create_text(14, H - 14, anchor="sw", text=footer[:48], fill=DIM, font=("Segoe UI", 8))
        c.create_text(W - 14, H - 14, anchor="se", text=(s.server or "").replace("ARE_", ""), fill=DIM,
                      font=("Segoe UI", 8))

    def _draw_guidance(self, g):
        c = self.c
        if g.status == "NAV":
            ang = g.relative if g.relative is not None else g.bearing
            self._arrow(50, 85, 30, ang, ROUTE)
            c.create_text(95, 62, anchor="nw", text=f"{g.distance:.0f} m", fill=FG, font=("Segoe UI", 20, "bold"))
            turn = ""
            if g.relative is not None:
                a = g.relative
                turn = "ahead" if abs(a) < 20 else ("behind" if abs(a) > 160 else
                       f"{'right' if a > 0 else 'left'} {abs(a):.0f}°")
            c.create_text(97, 98, anchor="nw", text=f"{compass(g.bearing)}  ·  {turn}", fill=DIM,
                          font=("Segoe UI", 10))
        elif g.status == "ARRIVED":
            c.create_text(W / 2, 80, text="✓", fill=ROUTE, font=("Segoe UI", 30, "bold"))
        c.create_text(14, 40, anchor="nw", text=g.line1, width=W - 28, fill=FG if g.status != "NO_ROUTE" else PIN,
                      font=("Segoe UI", 10))
        if g.line2:
            c.create_text(14, 124, anchor="nw", text=g.line2, width=W - 28, fill=DIM, font=("Segoe UI", 8))

    def _arrow(self, cx, cy, r, deg, color):
        a = math.radians(deg)
        pts = []
        for px, py in ((0, -r), (r * 0.6, r * 0.7), (0, r * 0.35), (-r * 0.6, r * 0.7)):
            pts += [cx + px * math.cos(a) - py * math.sin(a), cy + px * math.sin(a) + py * math.cos(a)]
        self.c.create_polygon(pts, fill=color, outline="")

    def _draw_map(self, s, g):
        c = self.c
        if self.pois_area != s.area:
            self.area_pois = self.store.db.execute(
                "SELECT kind,name,x,y FROM pois WHERE area=?", (s.area,)).fetchall()
            self.pois_area = s.area
        w_m = (s.size[0] or 0) * 10 if s.size else 0
        h_m = (s.size[1] or 0) * 10 if s.size else 0
        if not w_m or not h_m:   # unknown size: fit what we know
            xs = [p["x"] for p in self.area_pois] + [s.pos[0]]
            ys = [p["y"] for p in self.area_pois] + [s.pos[1]]
            w_m, h_m = max(xs) + 10, max(ys) + 10
        scale = (MAP_SIZE - 20) / max(w_m, h_m)
        ox = 10 + (MAP_SIZE - 20 - w_m * scale) / 2
        oy = MAP_Y + 10 + (MAP_SIZE - 20 - h_m * scale) / 2
        P = lambda x, y: (ox + x * scale, oy + (h_m - y) * scale)   # north up
        x0, y0 = P(0, h_m)
        x1, y1 = P(w_m, 0)
        c.create_rectangle(x0, y0, x1, y1, fill="#182027", outline="#2a3640")
        for i in range(1, int(w_m // 10)):
            c.create_line(P(i * 10, 0)[0], y0, P(i * 10, 0)[0], y1, fill="#1e2830")
        for j in range(1, int(h_m // 10)):
            c.create_line(x0, P(0, j * 10)[1], x1, P(0, j * 10)[1], fill="#1e2830")
        for p in self.area_pois:
            px, py = P(p["x"], p["y"])
            if p["kind"] == "pin":
                c.create_oval(px - 4, py - 4, px + 4, py + 4, fill=PIN, outline="")
                c.create_text(px + 6, py, anchor="w", text=(p["name"] or "")[:22], fill=PIN, font=("Segoe UI", 7))
            else:
                c.create_rectangle(px - 2, py - 2, px + 2, py + 2, fill=DOOR, outline="")
        mx, my = P(*s.pos[:2])
        if g and g.target:
            tx, ty = P(*g.target)
            c.create_line(mx, my, tx, ty, fill=ROUTE, dash=(4, 3), width=2)
            c.create_oval(tx - 7, ty - 7, tx + 7, ty + 7, outline=ROUTE, width=2)
        fx, fy = (s.facing or (0, 1, 0))[:2]
        self._arrow(mx, my, 8, math.degrees(math.atan2(fx, fy)), ME)


def main():
    Overlay(" ".join(a for a in sys.argv[1:])).run()


if __name__ == "__main__":
    main()
