"""Map window (experimental): the world map in a normal window you can put on any monitor (or beside a windowed
game). It follows you, shows the directions, and a click on a place sets the destination for the
in-game panel too.

  NWN-GPS.exe mapwindow       (the launcher starts it; it stays hidden until it's turned on)

Turn it on or off with Ctrl+Shift+W in the game, in Settings ("Map window"), or close it with its
X. It remembers where you put it and how big; the first time it fills a monitor the game isn't
on, or opens as a window if there's only one. It never takes the keyboard from the game: clicks
on it don't switch away from a fullscreen game, so its controls are buttons and the mouse.

Reads game memory the same read-only way as the recorder; changes nothing in the game.
"""
import ctypes
import ctypes.wintypes as wt
import json
import queue
import threading
import time

from PIL import Image, ImageDraw

from . import config, maps
from .db import DATA_DIR, Store, db_name
from .fullmap import FullMap, _text, fit_text
from .hud import read_target, resolve_target, set_target
from .nav import Navigator, compass
from .panel import _arrow
from .session import IN_GAME, UNSUPPORTED, Session

GEOMETRY_FILE = DATA_DIR / "map_window.json"
BAR = 76                    # frame pixels: directions strip above the map
MAX_FRAME = 1600            # largest frame we draw; bigger windows get it scaled up
MIN_W, MIN_H = 480, 320
CLICK_SLOP = 6              # window pixels a press may move and still count as a click
SETTINGS_EVERY = 1.0        # seconds between looks at settings.json
BG, BAR_BG = (10, 13, 16, 255), (16, 22, 28, 255)
FG, DIM, ROUTE, GOLD = (232, 238, 242, 255), (125, 138, 148, 255), (76, 217, 100, 255), (242, 201, 76, 255)
HINT = "click a place to go there    drag to look around    mouse wheel to zoom"
STATE_TEXT = {"NO_GAME": "Waiting for the game...", "MENU": "In menus", "LOADING": "Loading..."}

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_EXSTYLE = -20
WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x40000, 0x08000000
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetParent.restype = wt.HWND
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
MonitorEnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
MONITORINFOF_PRIMARY = 1


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


# ---- monitors and placement ----------------------------------------------------------------------
class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def monitors():
    """[{"work": (l, t, r, b), "screen": (l, t, r, b), "primary": bool}, ...] for every monitor."""
    out = []

    def cb(hmon, _hdc, _rc, _):
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            w, s = mi.rcWork, mi.rcMonitor
            out.append({"work": (w.left, w.top, w.right, w.bottom), "screen": (s.left, s.top, s.right, s.bottom),
                        "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY)})
        return True
    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    return out


def game_rect(pid):
    """Screen rect (l, t, r, b) of the game's biggest visible window, or None."""
    if not pid:
        return None
    best = []

    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            best.append(((r.right - r.left) * (r.bottom - r.top), (r.left, r.top, r.right, r.bottom)))
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return max(best)[1] if best else None


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def place(saved, mons, game=None):
    """Where to open: (x, y, w, h, maximised).

    The saved spot if it's still on a connected monitor (monitors come and go: laptops, TVs,
    tablets used as screens). Otherwise maximised on the biggest monitor the game isn't on, or,
    with a single monitor, a window filling most of it."""
    if not mons:
        return 100, 100, 1000, 700, False
    if saved:
        try:
            x, y, w, h = (int(saved[k]) for k in ("x", "y", "w", "h"))
            cx, cy = x + w // 2, y + min(h, 40) // 2            # the title bar must be reachable
            if w >= 200 and h >= 150 and any(m["work"][0] <= cx < m["work"][2] and m["work"][1] <= cy < m["work"][3]
                                             for m in mons):
                return x, y, w, h, bool(saved.get("zoomed"))
        except (KeyError, TypeError, ValueError):
            pass
    if game:
        free = [m for m in mons if _overlap(m["screen"], game) == 0]
    else:          # game not running (yet): it normally starts on the primary monitor
        free = [m for m in mons if not m["primary"]]
    if free:
        l, t, r, b = max(free, key=lambda m: (m["work"][2] - m["work"][0]) * (m["work"][3] - m["work"][1]))["work"]
        return l + 40, t + 40, max(MIN_W, (r - l) * 3 // 4), max(MIN_H, (b - t) * 3 // 4), True
    l, t, r, b = next((m for m in mons if m["primary"]), mons[0])["work"]
    w, h = max(MIN_W, (r - l) * 2 // 3), max(MIN_H, (b - t) * 2 // 3)
    return l + (r - l - w) // 2, t + (b - t - h) // 2, w, h, False


def frame_for(win_w, win_h, scale=1.0):
    """Size we draw at for a window of win_w x win_h pixels: the display scale (125 %, 150 % ...)
    makes text bigger, and very big windows get a MAX_FRAME frame scaled up (drawing is the slow part)."""
    win_w, win_h = max(1, win_w), max(1, win_h)
    s = min(1.0 / max(1.0, scale), MAX_FRAME / win_w, MAX_FRAME / win_h)
    return max(MIN_W, int(win_w * s)), max(MIN_H, int(win_h * s))


def load_geometry():
    try:
        g = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def save_geometry(g):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GEOMETRY_FILE.write_text(json.dumps(g), encoding="utf-8")
    except OSError:
        pass


def set_enabled(on):
    s = config.load_settings()
    if bool(s.get("map_window")) != on:
        s["map_window"] = on
        config.save_settings(s)


# ---- drawing ------------------------------------------------------------------------------------
def directions_bar(img, g, search_key):
    """The strip above the map: arrow, distance and the next step (or how to pick a destination)."""
    W = img.width
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, BAR), fill=BAR_BG)
    if g is None:
        _text(d, (24, BAR / 2), fit(d, f"No destination. Click a place on the map, or press {search_key} in the "
                                       "game to search.", 11, W - 48), 11, DIM, anchor="lm")
        return
    x = 24
    if g.status == "NAV":
        ang = g.relative if g.relative is not None else g.bearing
        _arrow(d, (x + 22) / 2, BAR / 4, 13, ang, ROUTE)          # _arrow works in half-size units
        x += 60
        dist = f"{g.distance:.0f} m"
        _text(d, (x, BAR / 2 - 12), dist, 16, FG, bold=True, anchor="lm")
        turn = ""
        if g.relative is not None:
            a = g.relative
            turn = "ahead" if abs(a) < 20 else ("behind" if abs(a) > 160 else f"{'right' if a > 0 else 'left'} {abs(a):.0f}°")
        _text(d, (x, BAR / 2 + 20), f"{compass(g.bearing)}  ·  {turn}", 9, DIM, anchor="lm")
        x += max(150, d.textlength(dist, font=_font(16, True)) + 30)
    elif g.status == "ARRIVED":
        _text(d, (x, BAR / 2), "✓", 18, ROUTE, bold=True, anchor="lm")
        x += 56
    room = W - x - 24
    _text(d, (x, BAR / 2 - (12 if g.line2 else 0)), fit(d, f"{g.dest_name}: {g.line1}", 11, room), 11,
          GOLD if g.status == "NO_ROUTE" else FG, anchor="lm")
    if g.line2:
        _text(d, (x, BAR / 2 + 18), fit(d, g.line2, 9, room), 9, DIM, anchor="lm")


def fit(d, text, size, width, bold=False):
    return fit_text(d, text, size, width, bold)


def _font(size, bold=False):
    from .panel import font
    return font(size, bold)


def message_frame(size, text, detail=""):
    img = Image.new("RGBA", size, BG)
    d = ImageDraw.Draw(img)
    _text(d, (size[0] / 2, size[1] / 2 - 14), text, 14, DIM, anchor="mm")
    if detail:
        _text(d, (size[0] / 2, size[1] / 2 + 30), detail, 9, DIM, anchor="mm")
    return img


# ---- the worker: reads the game, keeps the map, draws frames --------------------------------------
class Worker(threading.Thread):
    """Everything except the window itself (tkinter stays on the main thread): reading the game,
    the database, routing and drawing. Talks to the window through two queues."""

    def __init__(self):
        super().__init__(name="map-window", daemon=True)
        self.inputs, self.frames = queue.Queue(), queue.Queue(maxsize=1)
        self.enabled = False
        self.want = (1000, 700, 1.0)         # window width, height, display scale (set by the window)
        self.pid = None
        self.session, self.store, self.maps, self.fm = None, None, None, None
        self.nav, self.target, self.area, self.area_img, self.nwsync_host = None, object(), None, None, None
        self.last_key, self.redraw = None, True
        self.pin_labels = True
        self.inputs_status = None          # a message for the window's status line
        keys = config.load_settings()["hotkeys"]
        self.search_key, self.window_key = keys["search"], keys["window"]

    def run(self):
        while True:
            t0 = time.time()
            busy = False
            try:
                if self.enabled:
                    busy = self.tick()
                elif self.session:
                    self.stop_reading()
            except Exception as e:      # keep the window alive; the log says what went wrong
                log(f"map window: {e!r}")
                time.sleep(1.0)
            time.sleep(max(0.0, (0.03 if busy else (0.15 if self.enabled else 0.5)) - (time.time() - t0)))

    def stop_reading(self):
        log("map window off: stopped reading the game")
        self.session.close()
        self.session, self.pid = None, None
        if self.store:
            self.store.close()
        self.store, self.maps, self.fm, self.nav, self.target, self.area = None, None, None, None, object(), None
        self.last_key = None

    def open_world(self, world):
        if self.store and (not world or db_name(world) == db_name(self.store.world)):
            return
        if self.store:
            log(f"world: {world} (was {self.store.world})")
            self.store.close()
        self.store = Store(world) if world else Store()
        self.maps, self.fm, self.target, self.area, self.area_img = None, None, object(), None, None

    def ensure_map(self):
        if self.maps is None:
            from .resources import Resources
            self.maps = maps.Maps(Resources(self.nwsync_host))
        if self.fm is None:
            self.fm = FullMap(self.store, self.maps)
            self.fm.back_hint = "Back to me: follow you again"
            self.fm.pin_labels = self.pin_labels
            self.fm.rebuild()

    def handle_inputs(self, snap):
        busy = False
        while True:
            try:
                kind, *args = self.inputs.get_nowait()
            except queue.Empty:
                return busy
            busy = True
            if kind == "settings":
                self.search_key, self.window_key = args
                self.last_key = None
            elif self.fm is None:
                continue                      # no map drawn yet: nothing to drag or click
            elif kind == "drag":
                self.fm.drag(*args)
            elif kind == "zoom":
                self.fm.zoom(args[0])
            elif kind == "home":
                self.fm.reset_view()
            elif kind == "labels":
                self.pin_labels = self.fm.pin_labels = not self.fm.pin_labels
            elif kind == "click":
                fx, fy = args
                pick = self.fm.pick_at(fx, fy - BAR)
                if pick:
                    from .picker import remember
                    remember(pick)
                    set_target(None, pick=pick)
                    log(f"map window click: destination {pick['name']} ({pick['kind']} in {pick['area']})")
                    self.frames_msg(f"Destination: {pick['name']}")

    def frames_msg(self, text):
        self.inputs_status = text

    def tick(self):
        if self.session is None:
            log("map window on: reading the game")
            self.session = Session(log=log)
        snap = self.session.poll()
        self.pid = self.session.mem.pid if self.session.mem else None
        w, h, scale = self.want
        size = frame_for(w, h, scale)
        if snap.state == UNSUPPORTED:
            return self.show(("unsupported", size), lambda: message_frame(
                size, "This game version isn't supported yet", "NWN GPS refuses unknown game builds to stay safe"))
        if snap.state != IN_GAME:
            self.handle_inputs(snap)          # settings changes; map input waits for a map
            return self.show((snap.state, size, self.window_key), lambda: message_frame(
                size, STATE_TEXT.get(snap.state, "Starting..."), f"Map window  ·  {self.window_key} in the game turns it off"))
        if snap.nwsync and not self.nwsync_host:
            from urllib.parse import urlparse
            self.nwsync_host = urlparse(snap.nwsync).hostname
        self.open_world(snap.world)
        self.ensure_map()
        busy = self.handle_inputs(snap)
        tgt = read_target()
        if tgt != self.target:
            self.target = tgt
            dest = resolve_target(self.store, tgt)
            self.nav = Navigator(self.store, dest) if dest else None
        if snap.area != self.area:
            self.area = snap.area
            self.area_img = maps.area_image(self.maps, self.store, self.session.mem, snap, log)
        g = self.nav.update(snap) if self.nav else None
        data = self.fm.refresh()
        key = ("map", size, data, self.fm.view_key(), self.fm.pin_labels, snap.area, self.search_key,
               tuple(round(v * 2) for v in snap.pos[:2]) if snap.pos else None,
               tuple(round(v, 1) for v in snap.facing[:2]) if snap.facing else None,
               (g.status, g.line1, g.line2, round(g.distance or 0), g.target) if g else None)

        def draw():
            img = Image.new("RGBA", size, BG)
            img.alpha_composite(self.fm.render((size[0], size[1] - BAR), snap, g, self.nav, self.area_img,
                                               hint=HINT, footer_route=False), (0, BAR))
            directions_bar(img, g, self.search_key)
            return img
        self.show(key, draw)
        return busy

    def show(self, key, draw):
        if key == self.last_key and not self.redraw:
            return False
        img = draw()
        self.last_key, self.redraw = key, False
        try:
            self.frames.get_nowait()          # only the newest frame matters
        except queue.Empty:
            pass
        self.frames.put(img)
        return False


# ---- the window ---------------------------------------------------------------------------------
class MapWindow:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.worker = Worker()
        self.root = tk.Tk()
        self.root.title("NWN GPS map (experimental)")
        self.root.configure(bg="#0a0d10")
        self.root.minsize(MIN_W, MIN_H)
        self.root.withdraw()
        st = ttk.Style(self.root)                 # big enough to hit with a finger on a touch screen
        st.configure("Map.TButton", font=("Segoe UI", 11), padding=(12, 6))
        st.configure("Map.TCheckbutton", font=("Segoe UI", 11), padding=(8, 6))
        st.configure("Map.TLabel", font=("Segoe UI", 11))
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(side="top", fill="x")
        for text, msg in (("Back to me", ("home",)), ("Zoom in  +", ("zoom", 1)), ("Zoom out  -", ("zoom", -1)),
                          ("Pin names", ("labels",))):
            ttk.Button(bar, text=text, style="Map.TButton", command=lambda m=msg: self.send(*m)).pack(
                side="left", padx=(0, 6))
        self.on_top = tk.BooleanVar(value=bool(load_geometry().get("on_top")))
        ttk.Checkbutton(bar, text="Always on top", style="Map.TCheckbutton", variable=self.on_top,
                        command=self.apply_on_top).pack(side="left", padx=(8, 0))
        self.status = ttk.Label(bar, text="", style="Map.TLabel")
        self.status.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Hide", style="Map.TButton", command=self.hide_by_user).pack(side="right")
        self.canvas = tk.Canvas(self.root, bg="#0a0d10", highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="top", fill="both", expand=True)
        self.photo, self.frame_size, self.item = None, None, None
        self.press, self.moved, self.last_xy = None, 0, None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", lambda e: self.send("zoom", e.delta / 120))
        self.canvas.bind("<Configure>", self.on_resize)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_by_user)
        self.settings_mtime, self.shown, self.styled, self.save_pending = None, False, False, None

    # input -> worker (in frame pixels)
    def send(self, *msg):
        self.worker.inputs.put(msg)

    def to_frame(self, dx, dy):
        if not self.frame_size:
            return 0, 0
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        return dx * self.frame_size[0] / cw, dy * self.frame_size[1] / ch

    def on_press(self, e):
        self.press, self.last_xy, self.moved = (e.x, e.y), (e.x, e.y), 0

    def on_motion(self, e):
        if self.last_xy is None:
            return
        dx, dy = e.x - self.last_xy[0], e.y - self.last_xy[1]
        self.last_xy = (e.x, e.y)
        self.moved = max(self.moved, abs(e.x - self.press[0]) + abs(e.y - self.press[1]))
        if self.moved > CLICK_SLOP:
            self.send("drag", *self.to_frame(dx, dy))

    def on_release(self, e):
        if self.press and self.moved <= CLICK_SLOP:
            self.send("click", *self.to_frame(e.x, e.y))
        self.press = self.last_xy = None

    def on_resize(self, _e):
        self.worker.want = (self.canvas.winfo_width(), self.canvas.winfo_height(), self.dpi_scale())
        if self.save_pending:                 # save once the window stops moving / resizing
            self.root.after_cancel(self.save_pending)
        self.save_pending = self.root.after(800, self.remember)

    # window state
    def hwnd(self):
        return user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

    def dpi_scale(self):
        try:
            return max(1.0, user32.GetDpiForWindow(self.hwnd()) / 96)
        except (AttributeError, OSError):
            return 1.0

    def style(self):
        """Clicks never take the keyboard (or the screen) from the game; still on the taskbar."""
        h = self.hwnd()
        ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_APPWINDOW)
        self.styled = True

    def apply_on_top(self):
        self.root.attributes("-topmost", self.on_top.get())
        self.remember()

    def remember(self):
        self.save_pending = None
        if not self.shown:
            return
        zoomed = self.root.state() == "zoomed"
        g = load_geometry()
        if not zoomed:
            g.update(x=self.root.winfo_x(), y=self.root.winfo_y(), w=self.root.winfo_width(),
                     h=self.root.winfo_height())
        g.update(zoomed=zoomed, on_top=self.on_top.get())
        save_geometry(g)

    def show(self):
        x, y, w, h, zoomed = place(load_geometry(), monitors(), game_rect(self.worker.pid))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.deiconify()
        if zoomed:
            self.root.state("zoomed")
        self.root.attributes("-topmost", self.on_top.get())
        if not self.styled:
            self.root.after(50, self.style)
        self.shown = True
        log(f"map window shown at {w}x{h}+{x}+{y}{' (maximised)' if zoomed else ''}")

    def hide(self):
        self.remember()
        self.shown = False
        self.root.withdraw()
        log("map window hidden")

    def hide_by_user(self):
        set_enabled(False)          # so Ctrl+Shift+W / Settings turn it back on
        self.apply_enabled(False)

    def apply_enabled(self, on):
        self.worker.enabled = on
        if on and not self.shown:
            self.show()
        elif not on and self.shown:
            self.hide()

    def watch_settings(self):
        try:
            mtime = config.SETTINGS_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self.settings_mtime:
            self.settings_mtime = mtime
            s = config.load_settings()
            self.send("settings", s["hotkeys"]["search"], s["hotkeys"]["window"])
            self.apply_enabled(bool(s.get("map_window")))
        self.root.after(int(SETTINGS_EVERY * 1000), self.watch_settings)

    def pump(self):
        try:
            img = self.worker.frames.get_nowait()
        except queue.Empty:
            img = None
        if img is not None and self.shown:
            from PIL import ImageTk
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.frame_size = img.size
            if cw > 1 and ch > 1 and (cw, ch) != img.size:
                img = img.resize((cw, ch), Image.BILINEAR)
            self.photo = ImageTk.PhotoImage(img)
            if self.item is None:
                self.item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            else:
                self.canvas.itemconfigure(self.item, image=self.photo)
        msg = getattr(self.worker, "inputs_status", None)
        if msg:
            self.worker.inputs_status = None
            self.status.configure(text=msg)
            self.root.after(6000, lambda: self.status.configure(text=""))
        self.root.after(30, self.pump)

    def run(self):
        self.worker.start()
        self.root.after(0, self.watch_settings)
        self.root.after(30, self.pump)
        log("map window ready (turn it on with Ctrl+Shift+W in the game or in Settings)")
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)     # per-monitor: sharp on every screen
    except (AttributeError, OSError):
        pass
    from .single import single_instance
    single_instance("mapwindow")
    MapWindow().run()


if __name__ == "__main__":
    main()
