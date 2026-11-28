"""Draw the GPS panel as an RGBA image (Pillow). Used by the in-game renderer.

render(snap, guidance, pois, area_size) -> PIL.Image (W x H, straight alpha)
Drawn at 2x and downsampled for smooth edges.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .nav import compass

W, H = 320, 566
LEGEND_Y = H - 78          # hotkey legend rows
LEGEND2_Y = H - 56
DRAG_HINT_Y = H - 34       # "Ctrl+Shift + drag to move" (above the area/server footer)
TOAST_COLORS = {"ok": (76, 217, 100, 255), "info": (63, 193, 255, 255), "warn": (242, 201, 76, 255),
                "error": (255, 99, 99, 255)}
SS = 2                                  # supersampling factor
MAP_Y, MAP_SIZE, ARROW_Y = 178, 300, 108
MAP_RECT = (10, MAP_Y + 10, MAP_SIZE - 20, MAP_SIZE - 20)   # the mini map inside the panel (x, y, w, h)
BG = (16, 20, 24, 215)
FG, DIM = (232, 238, 242, 255), (125, 138, 148, 255)
PIN, DOOR, ME, ROUTE = (242, 201, 76, 255), (176, 122, 74, 255), (63, 193, 255, 255), (76, 217, 100, 255)
MAP_BG, MAP_EDGE, GRID = (24, 32, 39, 230), (42, 54, 64, 255), (30, 40, 48, 255)
ACCENT_RGBA = (63, 193, 255, 255)
_scaled = {}     # last scaled tile map (scaling every frame is wasted work)


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


STAR = (255, 214, 102, 255)         # your saved places
WARN = TOAST_COLORS["warn"]
PICKER_ROWS = 9                      # result rows that fit; the list scrolls to keep the selection in view
PICKER_TOP, PICKER_ROW_H = 92, 44    # first result row's text line, and the step between rows
TAGS = {"pin": "pin", "door": "door", "area": "area", "user": "saved", "spot": "spot", "clear": "",
        "save_here": "new saved place", "save_dest": "new saved place"}


def star(d, cx, cy, r, color, scale=SS, outline=(0, 0, 0, 230)):
    """A five-pointed star centred on (cx, cy), radius r (in unscaled pixels)."""
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(((cx + rr * math.cos(a)) * scale, (cy + rr * math.sin(a)) * scale))
    d.polygon(pts, fill=color, outline=outline)


def _map_label(ld, px, py, name, side, color, gap=6):
    """A marker's name on the mini map: right of it, or left when it would run off the edge, with
    a dark halo so it stays readable over the tile art."""
    label = (name or "")[:22]
    width = ld.textlength(label, font=font(7)) / SS
    lx, anchor = (px - gap, "rm") if px + gap + width > side - 2 else (px + gap, "lm")
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        _text(ld, lx + dx * 0.6, py + dy * 0.6, label, 7, (0, 0, 0, 220), anchor=anchor)
    _text(ld, lx, py, label, 7, color, anchor=anchor)


def picker_window(n, sel, rows=PICKER_ROWS):
    """First row to draw so the selected one is visible (it stays a few rows from the bottom)."""
    return max(0, min(sel - rows + 3, n - rows)) if n > rows else 0


def picker_row_at(picker, x, y):
    """Index in picker.results of the row drawn under panel pixel (x, y), or None."""
    if getattr(picker, "naming", None) or not picker.results or not 8 <= x < W - 8:
        return None
    top = PICKER_TOP - 3                                   # where the highlight of the first row starts
    if y < top:
        return None
    row = (y - top) // PICKER_ROW_H
    i = picker_window(len(picker.results), picker.sel) + row
    return i if row < PICKER_ROWS and i < len(picker.results) else None


def render_picker(picker, area_name):
    """The destination picker: query box + results list, or naming a place you're saving."""
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), radius=10 * SS, fill=BG)
    naming = getattr(picker, "naming", None)
    _text(d, 14, 12, "Name this place" if naming else "Where to?", 12, FG, bold=True)
    d.rounded_rectangle((12 * SS, 38 * SS, (W - 12) * SS, 66 * SS), radius=5 * SS, fill=INPUT_BG,
                        outline=ACCENT_RGBA, width=SS)
    q = picker.query
    shown = q if len(q) < 34 else "…" + q[-33:]
    _text(d, 20, 52, shown + "|", 11, FG, anchor="lm")
    if naming:
        suggest = naming.get("suggest") or area_name(naming["area"])
        if not q:
            _text(d, 24, 52, suggest[:34], 10, DIM, anchor="lm")
        _text(d, 14, 80, f"in {area_name(naming['area'])}"[:52], 9, DIM)
        _text(d, 14, 104, "Type a name and press Enter. Enter with nothing typed keeps the grey name.",
              9, DIM, width=W - 28)
        _legend(d, H - 20, [("Enter", "save"), ("Esc", "back")])
        return img.resize((W, H), Image.LANCZOS)
    if not q:
        _text(d, 24, 52, "type to search places, areas, pins", 10, DIM, anchor="lm")
    _text(d, 14, 76, "Results" if q.strip() else "Saved and recent", 8, DIM)
    y = PICKER_TOP
    if not picker.results:
        _text(d, 14, y, "No matches yet - explore with the recorder running" if q.strip()
              else "No saved or recent destinations", 9, DIM, width=W - 28)
    first = picker_window(len(picker.results), picker.sel)
    if first:
        _text(d, W - 14, 76, f"↑ {first} more", 8, DIM, anchor="ra")
    confirm = getattr(picker, "confirm", None)
    for i, r in enumerate(picker.results[first:first + PICKER_ROWS], start=first):
        if i == picker.sel:
            d.rounded_rectangle((8 * SS, (y - 3) * SS, (W - 8) * SS, (y + 38) * SS), radius=5 * SS, fill=SEL_BG)
        kind = r["kind"]
        saved = kind == "user"
        color = {"pin": PIN, "clear": ROUTE, "save_here": ROUTE, "save_dest": ROUTE}.get(kind, STAR if saved else FG)
        x = 16
        if saved:
            star(d, 22, y + 7, 6, STAR)
            x = 32
        _text(d, x, y, (r["name"] or "")[:40], 10, color, bold=(i == picker.sel))
        if saved and confirm is not None and confirm == r.get("id"):
            _text(d, 16, y + 18, "Press Delete again to remove", 8, WARN)
        elif kind == "save_dest" and r.get("suggest"):
            _text(d, 16, y + 18, f"{r['suggest']} · {area_name(r['area'])}"[:52], 8, DIM)
        elif r.get("area"):
            _text(d, 16, y + 18, f"{TAGS.get(kind, kind)} · {area_name(r['area'])}"[:52], 8, DIM)
        y += PICKER_ROW_H
    rest = len(picker.results) - first - PICKER_ROWS
    if rest > 0:
        _text(d, W - 14, y - 4, f"↓ {rest} more", 8, DIM, anchor="ra")
    sel = picker.results[picker.sel] if picker.results else None
    items = [("↑↓", "choose"), ("Enter", "go"), ("Esc", "cancel")]
    if sel and sel["kind"] == "user" and not q:
        items = [("↑↓", "choose"), ("Enter", "go"), ("Del", "remove"), ("Esc", "cancel")]
    _legend(d, H - 20, items)
    return img.resize((W, H), Image.LANCZOS)


LEGEND = [("Ctrl+Shift", [("F", "Search"), ("X", "Clear"), ("M", "Map"), ("G", "Hide")]),
          ("Ctrl+Shift", [("E", "Export map"), ("I", "Import maps")])]


KEYTEXT = {"search": "Ctrl+Shift+F", "clear": "Ctrl+Shift+X", "map": "Ctrl+Shift+M", "hide": "Ctrl+Shift+G",
           "export": "Ctrl+Shift+E", "import": "Ctrl+Shift+I", "labels": "Ctrl+Shift+L"}


def set_legend(rows, keytext=None):
    """Legend rows from hotkeys.legend_rows() and key names for messages (follow the settings)."""
    LEGEND[:] = rows
    if keytext:
        KEYTEXT.update(keytext)


def toast_banner(img, d, text, kind, y, width):
    """A coloured message strip (export/import results etc.)."""
    color = TOAST_COLORS.get(kind, TOAST_COLORS["info"])
    f = font(9)
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) > (width - 36) * SS and cur:
            lines.append(cur)
            cur = word
        else:
            cur = t
    lines = (lines + [cur])[:3]
    h = 12 + 14 * len(lines)
    d.rounded_rectangle((8 * SS, y * SS, (8 + width - 16) * SS, (y + h) * SS), radius=6 * SS,
                        fill=(16, 22, 28, 245), outline=color, width=2 * SS)
    d.rectangle((8 * SS, y * SS, 13 * SS, (y + h) * SS), fill=color)
    for i, ln in enumerate(lines):
        d.text((20 * SS, (y + 7 + i * 14) * SS), ln, font=f, fill=FG)


def _fit(d, s, f, width):
    """s shortened with an ellipsis to fit `width` panel pixels."""
    if d.textlength(s, font=f) <= width * SS:
        return s
    while s and d.textlength(s + "…", font=f) > width * SS:
        s = s[:-1]
    return s.rstrip() + "…" if s else ""


def _title(d, area_name):
    """'NWN GPS' and, dimmed after it, the area you're in."""
    title = "NWN GPS"
    _text(d, 14, 12, title, 11, FG, bold=True)
    if area_name:
        x = 14 + d.textlength(title, font=font(11, True)) / SS + 8
        f = font(9)
        name = _fit(d, area_name, f, W - 14 - x)
        _text(d, x, 14, name, 9, DIM)


def render(snap, g, pois, area_size=None, map_img=None, toast=None, inbox=0, pan=(0, 0)):
    """pan: (x, y) panel pixels the mini map is dragged by (looking around; 0, 0 = following you)."""
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), radius=10 * SS, fill=BG)
    for y, (prefix, items) in zip((LEGEND_Y, LEGEND2_Y), LEGEND):
        _legend(d, y, items, prefix=prefix)
    if toast:
        toast_banner(img, d, toast[0], toast[1], MAP_Y + 14, W)
    elif inbox:
        toast_banner(img, d, f"{inbox} shared map{'s' if inbox > 1 else ''} in your Inbox - "
                             f"{KEYTEXT['import']} to import", "info", MAP_Y + 14, W)
    _text(d, W / 2, DRAG_HINT_Y, "Drag the map to look around  ·  Ctrl+Shift + drag to move the panel", 7, DIM,
          anchor="mm")
    if g:
        _text(d, 14, 12, g.dest_name[:34], 11, FG, bold=True)
    else:
        _title(d, snap.area_name or snap.area if snap and snap.state == "IN_GAME" else None)
    if snap is None or snap.state != "IN_GAME":
        msg = {"NO_GAME": "Waiting for the game...", "MENU": "In menus", "LOADING": "Loading..."}.get(
            snap.state if snap else "", "Starting...")
        _text(d, W / 2, 90, msg, 12, DIM, anchor="mm")
        return img.resize((W, H), Image.LANCZOS)
    if g:
        _guidance(d, g)
    else:
        _text(d, 14, 40, f"No destination. Press {KEYTEXT['search']} to choose one.", 10, DIM, width=W - 28)
    _map(img, d, snap, g, pois, area_size, map_img, pan)
    if toast:     # draw messages on top of the map
        toast_banner(img, d, toast[0], toast[1], MAP_Y + 14, W)
    elif inbox:
        toast_banner(img, d, f"{inbox} shared map{'s' if inbox > 1 else ''} in your Inbox - "
                             f"{KEYTEXT['import']} to import", "info", MAP_Y + 14, W)
    if g:     # without a destination the area is in the title already
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


PIN_SNAP_DIST = 7.0   # metres: a map pin this close to a door is drawn on that door


def display_pois(pois):
    """Map pins snapped onto the door they label (builders place map-note waypoints a few metres
    beside the doorway). Display only: the database keeps the true positions."""
    doors = [p for p in pois if p["kind"] == "door"]
    out = []
    for p in pois:
        p = dict(p)
        if p["kind"] == "pin" and doors:
            near = min(doors, key=lambda dr: (dr["x"] - p["x"]) ** 2 + (dr["y"] - p["y"]) ** 2)
            if math.hypot(near["x"] - p["x"], near["y"] - p["y"]) <= PIN_SNAP_DIST:
                p["x"], p["y"] = near["x"], near["y"]
        out.append(p)
    return out


FOLLOW_VIEW = 120.0   # metres: larger areas show a window this big centred on you
ART_PPM = 3.2         # tile-art pixels per metre (32 px per 10 m tile)


def _view(s, w_m, h_m, pan_m=(0.0, 0.0)):
    """(left, top, size) of the visible square in world metres (top = north edge). pan_m moves the
    window's centre away from the player (dragging the map); it stays inside the area."""
    big = max(w_m, h_m)
    if big <= FOLLOW_VIEW:                       # whole area, centred (nothing to look around for)
        v = big
        cx, cy = w_m / 2, h_m / 2
    else:                                        # follow the player, clamped to the area
        v = FOLLOW_VIEW
        px, py = s.pos[0] + pan_m[0], s.pos[1] + pan_m[1]
        cx = min(max(px, v / 2), w_m - v / 2) if w_m > v else w_m / 2
        cy = min(max(py, v / 2), h_m - v / 2) if h_m > v else h_m / 2
    return cx - v / 2, cy + v / 2, v


def pan_metres(pan_px, view=FOLLOW_VIEW):
    """Mouse drag on the mini map (panel pixels, y down) -> how far the view centre moves (metres,
    y north). Dragging the map right shows what's west of you, like grabbing paper."""
    scale = MAP_RECT[2] / view
    return -pan_px[0] / scale, pan_px[1] / scale


def _map(img, d, s, g, pois, area_size, map_img=None, pan=(0, 0)):
    w_m, h_m = (area_size[0] * 10, area_size[1] * 10) if area_size and all(area_size) else (0, 0)
    if not w_m or not h_m:
        xs = [p["x"] for p in pois] + [s.pos[0]]
        ys = [p["y"] for p in pois] + [s.pos[1]]
        w_m, h_m = max(xs) + 10, max(ys) + 10
    side = MAP_SIZE - 20                         # panel pixels
    left, top, v = _view(s, w_m, h_m, pan_metres(pan))
    scale = side / v                             # panel pixels per metre

    def P(x, y):                                 # world -> layer pixels (not supersampled)
        return ((x - left) * scale, (top - y) * scale)

    layer = Image.new("RGBA", (side * SS, side * SS), MAP_BG)
    ld = ImageDraw.Draw(layer)
    has_art = map_img is not None and area_size and map_img.size == (area_size[0] * 32, area_size[1] * 32)
    if has_art:
        box = (round(left * ART_PPM), round((h_m - top) * ART_PPM),
               round((left + v) * ART_PPM), round((h_m - top + v) * ART_PPM))
        ck = (id(map_img), box, side)
        if _scaled.get("key") != ck:             # crop pads outside the area with transparency
            _scaled.update(key=ck, img=map_img.crop(box).resize((side * SS, side * SS), Image.BILINEAR))
        layer.alpha_composite(_scaled["img"])
    else:
        for i in range(0, int(w_m // 10) + 1):
            gx = P(i * 10, 0)[0] * SS
            ld.line((gx, P(0, h_m)[1] * SS, gx, P(0, 0)[1] * SS), fill=GRID, width=1)
        for j in range(0, int(h_m // 10) + 1):
            gy = P(0, j * 10)[1] * SS
            ld.line((P(0, 0)[0] * SS, gy, P(w_m, 0)[0] * SS, gy), fill=GRID, width=1)
    for p in display_pois(pois):
        px, py = P(p["x"], p["y"])
        if p["kind"] == "door" and has_art:
            continue        # the tile art already shows doors; a second marker beside it looks misaligned
        if p["kind"] == "user":
            if 0 <= px <= side and 0 <= py <= side:
                star(ld, px, py, 8, STAR)
                _map_label(ld, px, py, p["name"], side, STAR, gap=10)
            continue
        if p["kind"] == "pin" and not (0 <= px <= side and 0 <= py <= side):
            _edge_pointer(ld, px, py, side)     # outside the follow window: point to it from the border
        elif p["kind"] == "pin":
            ld.ellipse(((px - 4) * SS, (py - 4) * SS, (px + 4) * SS, (py + 4) * SS), fill=PIN,
                       outline=(0, 0, 0, 200), width=SS)
            _map_label(ld, px, py, p["name"], side, PIN)
        else:
            ld.rectangle(((px - 2) * SS, (py - 2) * SS, (px + 2) * SS, (py + 2) * SS), fill=DOOR)
    _route_and_player(ld, s, g, pois, P)
    mx, my = P(*s.pos[:2])
    if not (0 <= mx <= side and 0 <= my <= side):
        _edge_pointer(ld, mx, my, side, ME, size=1.6)   # looking elsewhere: this way back to you
    ox, oy = MAP_RECT[0], MAP_RECT[1]
    img.alpha_composite(layer, (ox * SS, oy * SS))
    d.rectangle((ox * SS, oy * SS, (ox + side) * SS, (oy + side) * SS), outline=MAP_EDGE, width=SS)
    if v < max(w_m, h_m):
        _text(d, ox + side - 4, oy + side - 4, f"{v:.0f} m view", 7, DIM, anchor="rs")


EDGE_INSET = 7        # panel pixels: off-window pin pointers sit this far inside the map border


def _edge_pointer(d, px, py, side, color=PIN, size=1.0):
    """A small arrow on the map's border, pointing at a pin (or you) outside the visible window."""
    c = side / 2
    dx, dy = px - c, py - c
    t = (c - EDGE_INSET) / max(abs(dx), abs(dy))            # scale onto the inset square
    ex, ey = c + dx * t, c + dy * t
    ang = math.atan2(dy, dx)
    tip = (ex + 5 * size * math.cos(ang), ey + 5 * size * math.sin(ang))
    back = [(ex + 4 * size * math.cos(ang + a), ey + 4 * size * math.sin(ang + a)) for a in (2.4, -2.4)]
    d.polygon([(x * SS, y * SS) for x, y in (tip, *back)], fill=color, outline=(0, 0, 0, 220))


def _route_and_player(d, s, g, pois, P):
    mx, my = P(*s.pos[:2])
    if g and g.target:
        target = g.target
        doors = [p for p in pois if p["kind"] == "door"]
        if doors:   # exits are recorded where you stood; draw them on the doorway itself
            near = min(doors, key=lambda dr: (dr["x"] - target[0]) ** 2 + (dr["y"] - target[1]) ** 2)
            if math.hypot(near["x"] - target[0], near["y"] - target[1]) <= PIN_SNAP_DIST:
                target = (near["x"], near["y"])
        tx, ty = P(*target)
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
