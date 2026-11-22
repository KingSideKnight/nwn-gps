"""Draw the GPS panel as an RGBA image (Pillow). Used by the in-game renderer.

render(snap, guidance, pois, area_size) -> PIL.Image (W x H, straight alpha)
Drawn at 2x and downsampled for smooth edges.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .nav import compass

W, H = 320, 528
LEGEND_Y = H - 40          # hotkey legend row (above the area/server footer)
SS = 2                                  # supersampling factor
MAP_Y, MAP_SIZE, ARROW_Y = 178, 300, 108
BG = (16, 20, 24, 215)
FG, DIM = (232, 238, 242, 255), (125, 138, 148, 255)
PIN, DOOR, ME, ROUTE = (242, 201, 76, 255), (176, 122, 74, 255), (63, 193, 255, 255), (76, 217, 100, 255)
MAP_BG, MAP_EDGE, GRID = (24, 32, 39, 230), (42, 54, 64, 255), (30, 40, 48, 255)
ACCENT_RGBA = (63, 193, 255, 255)


@lru_cache(maxsize=16)
def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size * SS)
        except OSError:
            continue
    return ImageFont.load_default()


def _arrow(d, cx, cy, r, deg, color):
    a = math.radians(deg)
    pts = []
    for px, py in ((0, -r), (r * 0.6, r * 0.7), (0, r * 0.35), (-r * 0.6, r * 0.7)):
        pts.append(((cx + px * math.cos(a) - py * math.sin(a)) * SS, (cy + px * math.sin(a) + py * math.cos(a)) * SS))
    d.polygon(pts, fill=color)


KEY_BG, KEY_EDGE = (34, 44, 54, 255), (70, 86, 100, 255)


def _legend(d, y, items, prefix=None):
    """Hotkey chips centred on row y: [prefix +] [key] label  [key] label ..."""
    fk, fl = font(8, True), font(8)
    pad, gap = 4, 10
    parts = []
    if prefix:
        parts.append(("text", prefix + " +"))
    for key, label in items:
        parts += [("key", key), ("text", label)]
    widths = [d.textlength(t, font=fk if k == "key" else fl) / SS + (2 * pad if k == "key" else 0)
              for k, t in parts]
    total = sum(widths) + 4 * (len(parts) - 1) + gap * (len(items) - 1)
    x = (W - total) / 2
    for i, ((k, t), w) in enumerate(zip(parts, widths)):
        if k == "key":
            d.rounded_rectangle((x * SS, (y - 8) * SS, (x + w) * SS, (y + 8) * SS), radius=3 * SS,
                                fill=KEY_BG, outline=KEY_EDGE, width=SS)
            d.text(((x + w / 2) * SS, y * SS), t, font=fk, fill=FG, anchor="mm")
        else:
            d.text((x * SS, y * SS), t, font=fl, fill=DIM, anchor="lm")
        x += w + 4
        if k == "text" and i > 0 and i < len(parts) - 1:
            x += gap


def _text(d, x, y, s, size, color, bold=False, anchor="la", width=None):
    f = font(size, bold)
    if width:   # simple word wrap
        lines, cur = [], ""
        for w in s.split():
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) > width * SS and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
        for i, ln in enumerate(lines[:3]):
            d.text((x * SS, (y + i * (size + 4)) * SS), ln, font=f, fill=color, anchor=anchor)
        return
    d.text((x * SS, y * SS), s, font=f, fill=color, anchor=anchor)


SEL_BG, INPUT_BG = (40, 62, 80, 255), (28, 36, 44, 255)


def render_picker(picker, area_name):
    """The destination picker: query box + results list."""
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), radius=10 * SS, fill=BG)
    _text(d, 14, 12, "Where to?", 12, FG, bold=True)
    d.rounded_rectangle((12 * SS, 38 * SS, (W - 12) * SS, 66 * SS), radius=5 * SS, fill=INPUT_BG,
                        outline=ACCENT_RGBA, width=SS)
    q = picker.query
    shown = q if len(q) < 34 else "…" + q[-33:]
    _text(d, 20, 52, shown + "|", 11, FG, anchor="lm")
    if not q:
        _text(d, 24, 52, "type to search areas, pins, doors", 10, DIM, anchor="lm")
    label = "Results" if q.strip() else "Recent"
    _text(d, 14, 76, label, 8, DIM)
    y = 92
    if not picker.results:
        _text(d, 14, y, "No matches yet - explore with the recorder running" if q.strip()
              else "No recent destinations", 9, DIM, width=W - 28)
    for i, r in enumerate(picker.results):
        if i == picker.sel:
            d.rounded_rectangle((8 * SS, (y - 3) * SS, (W - 8) * SS, (y + 38) * SS), radius=5 * SS, fill=SEL_BG)
        color = PIN if r["kind"] == "pin" else (ROUTE if r["kind"] == "clear" else FG)
        tag = {"pin": "pin", "door": "door", "area": "area", "user": "mark", "clear": ""}.get(r["kind"], r["kind"])
        _text(d, 16, y, (r["name"] or "")[:40], 10, color, bold=(i == picker.sel))
        if r.get("area"):
            _text(d, 16, y + 18, f"{tag} · {area_name(r['area'])}"[:52], 8, DIM)
        y += 44
        if y > H - 50:
            break
    _legend(d, H - 20, [("↑↓", "choose"), ("Enter", "go"), ("Esc", "cancel")])
    return img.resize((W, H), Image.LANCZOS)


HOTKEYS = [("F", "Search"), ("X", "Clear"), ("G", "Hide")]


def render(snap, g, pois, area_size=None):
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), radius=10 * SS, fill=BG)
    _legend(d, LEGEND_Y, HOTKEYS, prefix="Ctrl+Shift")
    _text(d, 14, 12, (g.dest_name if g else "GPS")[:34], 11, FG, bold=True)
    if snap is None or snap.state != "IN_GAME":
        msg = {"NO_GAME": "Waiting for the game...", "MENU": "In menus", "LOADING": "Loading..."}.get(
            snap.state if snap else "", "Starting...")
        _text(d, W / 2, 90, msg, 12, DIM, anchor="mm")
        return img.resize((W, H), Image.LANCZOS)
    if g:
        _guidance(d, g)
    else:
        _text(d, 14, 40, "No destination. Press Ctrl+Shift+F to choose one.", 10, DIM, width=W - 28)
    _map(d, snap, g, pois, area_size)
    _text(d, 14, H - 12, (snap.area_name or snap.area or "")[:46], 8, DIM, anchor="ls")
    _text(d, W - 14, H - 12, (snap.server or "").replace("ARE_", ""), 8, DIM, anchor="rs")
    return img.resize((W, H), Image.LANCZOS)


def _guidance(d, g):
    if g.status == "NAV":
        ang = g.relative if g.relative is not None else g.bearing
        _arrow(d, 50, ARROW_Y, 28, ang, ROUTE)
        _text(d, 95, ARROW_Y - 24, f"{g.distance:.0f} m", 20, FG, bold=True)
        turn = ""
        if g.relative is not None:
            a = g.relative
            turn = "ahead" if abs(a) < 20 else ("behind" if abs(a) > 160 else
                                                 f"{'right' if a > 0 else 'left'} {abs(a):.0f}°")
        _text(d, 97, ARROW_Y + 12, f"{compass(g.bearing)}  ·  {turn}", 10, DIM)
    elif g.status == "ARRIVED":
        _text(d, W / 2, ARROW_Y, "✓", 30, ROUTE, bold=True, anchor="mm")
    _text(d, 14, 36, g.line1, 10, PIN if g.status == "NO_ROUTE" else FG, width=W - 28)
    if g.line2:
        _text(d, 14, ARROW_Y + 42, g.line2, 8, DIM, width=W - 28)


def _map(d, s, g, pois, area_size):
    w_m, h_m = (area_size[0] * 10, area_size[1] * 10) if area_size and all(area_size) else (0, 0)
    if not w_m or not h_m:
        xs = [p["x"] for p in pois] + [s.pos[0]]
        ys = [p["y"] for p in pois] + [s.pos[1]]
        w_m, h_m = max(xs) + 10, max(ys) + 10
    scale = (MAP_SIZE - 20) / max(w_m, h_m)
    ox = 10 + (MAP_SIZE - 20 - w_m * scale) / 2
    oy = MAP_Y + 10 + (MAP_SIZE - 20 - h_m * scale) / 2

    def P(x, y):
        return (ox + x * scale, oy + (h_m - y) * scale)

    x0, y0 = P(0, h_m)
    x1, y1 = P(w_m, 0)
    d.rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), fill=MAP_BG, outline=MAP_EDGE, width=SS)
    for i in range(1, int(w_m // 10)):
        gx = P(i * 10, 0)[0] * SS
        d.line((gx, y0 * SS, gx, y1 * SS), fill=GRID, width=1)
    for j in range(1, int(h_m // 10)):
        gy = P(0, j * 10)[1] * SS
        d.line((x0 * SS, gy, x1 * SS, gy), fill=GRID, width=1)
    for p in pois:
        px, py = P(p["x"], p["y"])
        if p["kind"] == "pin":
            d.ellipse(((px - 4) * SS, (py - 4) * SS, (px + 4) * SS, (py + 4) * SS), fill=PIN)
            _text(d, px + 6, py, (p["name"] or "")[:22], 7, PIN, anchor="lm")
        else:
            d.rectangle(((px - 2) * SS, (py - 2) * SS, (px + 2) * SS, (py + 2) * SS), fill=DOOR)
    mx, my = P(*s.pos[:2])
    if g and g.target:
        tx, ty = P(*g.target)
        _dashed(d, mx, my, tx, ty, ROUTE)
        d.ellipse(((tx - 7) * SS, (ty - 7) * SS, (tx + 7) * SS, (ty + 7) * SS), outline=ROUTE, width=2 * SS)
    fx, fy = (s.facing or (0, 1, 0))[:2]
    _arrow(d, mx, my, 8, math.degrees(math.atan2(fx, fy)), ME)


def _dashed(d, x0, y0, x1, y1, color, dash=4, gap=3):
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    t = 0.0
    while t < length:
        e = min(t + dash, length)
        d.line(((x0 + ux * t) * SS, (y0 + uy * t) * SS, (x0 + ux * e) * SS, (y0 + uy * e) * SS),
               fill=color, width=2 * SS)
        t = e + gap
