"""Full-screen map (Ctrl+Shift+M): the stitched world map around you, with your position,
the route across areas and the destination. Falls back to the current area's own map when
that area isn't linked into the world map yet. Drawn at reduced resolution; the DLL scales
it to the game window on the GPU."""
import math

from PIL import Image, ImageDraw

from . import worldmap
from .panel import KEYTEXT, TOAST_COLORS, _arrow, _dashed, display_pois, font

BG = (10, 13, 16, 225)
FG, DIM, ROUTE, ME, GOLD = (232, 238, 242, 255), (125, 138, 148, 255), (76, 217, 100, 255), \
    (63, 193, 255, 255), (242, 201, 76, 255)
HEADER, FOOTER, PAD = 56, 34, 24
MAX_VIEW = 1200.0     # metres across: bigger clusters show a window this wide that follows you
MIN_SPAN = 150.0      # metres across: closest zoom
ZOOM_STEP = 1.25      # one wheel notch / one +/- press
PAN_STEP = 0.25       # an arrow key scrolls this share of the view
HIT_RADIUS = 14       # frame pixels: a click this close to a marker picks the marker


def frame_size(view_w, view_h, max_w=1600):
    """Render size with the game window's aspect ratio (the DLL scales it up)."""
    if not view_w or not view_h or not (100 <= view_w <= 16384 and 100 <= view_h <= 16384):
        return 1600, 900          # missing or implausible window size (it comes from shared memory)
    s = min(1.0, max_w / view_w, 1600 / view_h)
    return min(2048, max(640, int(view_w * s))), min(2048, max(360, int(view_h * s)))


def _text(d, xy, s, size, color, bold=False, anchor="la"):
    d.text(xy, s, font=font(size, bold), fill=color, anchor=anchor)   # font() sizes are SS-scaled


class FullMap:
    def __init__(self, store, maps):
        self.store, self.maps = store, maps
        self.world, self.cache, self.built_version = None, {}, None
        self.pin_labels = True       # pin names on / off (Ctrl+Shift+L, remembered in ui.json)
        # scrolling / zooming: center None = follow you; span None = default zoom
        self.center, self.span, self.view_cid = None, None, None
        self.last_view, self.last_px_per_m = None, None
        self.clickable = None        # what the last frame drew, for click to go (see pick_at)

    # --- scrolling and zooming (mouse drag / wheel, arrows, +/-, Home) ---------------------------
    def reset_view(self):
        """Back to following you at the default zoom."""
        self.center = self.span = None

    def view_key(self):
        """Part of the in-game render key: redraw when the view moves."""
        c = self.center and (round(self.center[0]), round(self.center[1]))
        return c, self.span and round(self.span)

    def _current(self):
        if self.last_view is None:
            return None
        x0, y0, x1, y1 = self.last_view
        return ((x0 + x1) / 2, (y0 + y1) / 2), x1 - x0

    def drag(self, fx, fy):
        """Drag the map by (fx, fy) frame pixels (right / down positive): the map follows the mouse."""
        cur = self._current()
        if cur is None or not self.last_px_per_m or not (fx or fy):
            return
        cx, cy = self.center or cur[0]
        self.center = (cx - fx / self.last_px_per_m, cy + fy / self.last_px_per_m)

    def pan(self, sx, sy):
        """Scroll by a share of the view: sx +1 = east, sy +1 = north."""
        cur = self._current()
        if cur is None:
            return
        (cx, cy), span = self.center or cur[0], cur[1]
        self.center = (cx + sx * PAN_STEP * span, cy + sy * PAN_STEP * span)

    def zoom(self, steps):
        """steps > 0 zooms in."""
        cur = self._current()
        if cur is None or not steps:
            return
        self.span = cur[1] / ZOOM_STEP ** steps

    # --- click to go ----------------------------------------------------------------------------
    def pick_at(self, fx, fy):
        """Destination under frame pixel (fx, fy) of the last frame: the nearest marker (building
        or map pin) within HIT_RADIUS, else that spot of the area under the click. None if the
        click was off the map."""
        c = self.clickable
        if c is None:
            return None
        box = c["box"]
        if not (box[0] <= fx <= box[2] and box[1] <= fy <= box[3]):
            return None
        near = [(math.hypot(px - fx, py - fy), dest) for px, py, dest in c["hits"]]
        near = [n for n in near if n[0] <= HIT_RADIUS]
        if near:
            return dict(min(near, key=lambda n: n[0])[1])
        area, x, y = c["spot"](fx, fy)
        if area is None:
            return None
        return {"kind": "spot", "area": area, "name": f"Spot in {worldmap.short_name(self.store.area_name(area))}",
                "x": round(x, 1), "y": round(y, 1)}

    def version(self):
        """Changes whenever the recorder (another process) adds areas, adds or distrusts links,
        or saves / replaces an area map."""
        db = self.store.db
        return (db.execute("SELECT COUNT(*) FROM areas").fetchone()[0],
                *self.store.links_version(),
                *db.execute("SELECT COUNT(*), MAX(seen) FROM area_tiles").fetchone())

    def rebuild(self):
        self.built_version = self.version()
        self.world = worldmap.build(self.store, self.maps)

    def refresh(self):
        """Rebuild if the database changed since the last build. Returns the current version."""
        v = self.version()
        if v != self.built_version or self.world is None:
            self.rebuild()
        return v

    def render(self, size, snap, g, nav, area_map_img, toast=None):
        W, H = size
        img = Image.new("RGBA", (W, H), BG)
        d = ImageDraw.Draw(img)
        self.refresh()
        home, hx, hy = worldmap.home_of(self.world, snap.area) if snap.area else (None, None, None)
        box = (PAD, HEADER, W - PAD, H - FOOTER)
        if home is not None:
            cid = self.world.cluster[home]
            title = "World map"
            here = self.world.to_world(home, *(snap.pos[:2] if hx is None else (hx, hy)))
            if cid != self.view_cid:          # another map (e.g. after a boat): start on you again
                self.reset_view()
                self.view_cid = cid
            view = self._view(cid, here, (box[2] - box[0]) / (box[3] - box[1]))
            self.last_view = view
            self.last_px_per_m = min((box[2] - box[0]) / (view[2] - view[0]), (box[3] - box[1]) / (view[3] - view[1]))
            hits = []
            src, P = worldmap.render_view(self.world, self.store, self.maps, cid, view,
                                          box[2] - box[0], box[3] - box[1],
                                          pin_labels=self.pin_labels, hits=hits)
            img.alpha_composite(src, (box[0], box[1]))
            self.clickable = {"box": box, "hits": [(box[0] + px, box[1] + py, dest) for px, py, dest in hits],
                              "spot": self._world_spot(cid, P, box)}
            to_px = lambda x, y: (box[0] + x, box[1] + y)       # noqa: E731
            me = to_px(*P(*here))
            route = self._route_points(snap, nav, P, to_px)
            inside = None if hx is None else snap.area_name
            if self.center is not None:
                _text(d, (box[2] - 8, box[3] - 8), f"{view[2] - view[0]:.0f} m view - Home: back to you", 8,
                      DIM, anchor="rs")
            elif view != self.world.bounds(cid):
                _text(d, (box[2] - 8, box[3] - 8), f"{view[2] - view[0]:.0f} m view, following you", 8, DIM,
                      anchor="rs")
        else:                                              # area not linked yet: its own map
            title = "Area map (not linked to the world map yet)"
            me, route, inside = self._area_only(img, snap, area_map_img, box), [], None
        # route + destination
        if route:
            pts = [me] + route
            for a, b in zip(pts, pts[1:]):
                _dashed(d, a[0] / 2, a[1] / 2, b[0] / 2, b[1] / 2, ROUTE)    # _dashed works in SS=2 units
            ex, ey = pts[-1]
            d.ellipse((ex - 9, ey - 9, ex + 9, ey + 9), outline=ROUTE, width=3)
        fx, fy = (snap.facing or (0, 1, 0))[:2]
        if box[0] <= me[0] <= box[2] and box[1] <= me[1] <= box[3]:     # you may be scrolled out of view
            _arrow(d, me[0] / 2, me[1] / 2, 9, math.degrees(math.atan2(fx, fy)), ME)
        # header / footer
        _text(d, (PAD, 16), title, 13, FG, bold=True)
        where = snap.area_name or ""
        if inside:
            where += "  (inside - shown at its door)"
        _text(d, (W - PAD, 18), where[:90], 9, DIM, anchor="ra")
        if g:
            _text(d, (PAD, H - 12), f"To {g.dest_name}: {g.line1}"[:140], 9, FG, anchor="ls")
        hint = "click  go there    " + ("drag / arrows scroll    wheel / +- zoom    " if home is not None else "")
        _text(d, (W - PAD, H - 12), f"{hint}{KEYTEXT['labels']}  pin names {'off' if self.pin_labels else 'on'}"
                                    f"    Esc  close", 9, DIM, anchor="rs")
        if toast:
            color = TOAST_COLORS.get(toast[1], TOAST_COLORS["info"])
            tw = d.textlength(toast[0], font=font(10)) + 40
            x0 = (W - tw) / 2
            d.rounded_rectangle((x0, HEADER + 10, x0 + tw, HEADER + 48), radius=8, fill=(16, 22, 28, 245),
                                outline=color, width=3)
            _text(d, (W / 2, HEADER + 29), toast[0], 10, FG, anchor="mm")
        return img

    def _view(self, cid, here, aspect):
        """Default: the whole cluster if it fits in MAX_VIEW metres, else a MAX_VIEW window on you.
        Scrolled / zoomed: centred on self.center, self.span metres across. Always clamped so the
        map can't be scrolled away entirely."""
        x0, y0, x1, y1 = self.world.bounds(cid)
        fit = max(x1 - x0, (y1 - y0) * aspect)            # span that shows the whole cluster
        if self.span is None and self.center is None and fit <= MAX_VIEW:
            return (x0, y0, x1, y1)
        span = self.span if self.span is not None else min(MAX_VIEW, fit)
        span = min(max(span, MIN_SPAN), max(fit, MIN_SPAN))
        if self.span is not None:
            self.span = span                              # don't let wheel steps pile up past the limits
        vw, vh = span, span / aspect

        def clamp(c, lo, hi, size):
            return (lo + hi) / 2 if hi - lo <= size else min(max(c, lo + size / 2), hi - size / 2)
        cx, cy = self.center or here
        cx, cy = clamp(cx, x0, x1, vw), clamp(cy, y0, y1, vh)
        if self.center is not None:
            self.center = (cx, cy)                        # stop at the map's edges
        return (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)

    def _world_spot(self, cid, P, box):
        """frame pixel -> (area, x, y in that area) on the world map, (None, ...) off every area."""
        (ax, ay), (bx, _) = P(0, 0), P(1, 1)
        ppm = bx - ax                                   # P is x -> ax + x * ppm, y -> ay - y * ppm
        world = self.world

        def spot(fx, fy):
            wx, wy = (fx - box[0] - ax) / ppm, (ay - (fy - box[1])) / ppm
            area = worldmap.area_at(world, cid, wx, wy)
            if area is None:
                return None, None, None
            ox, oy = world.origin[area]
            return area, wx - ox, wy - oy
        return spot

    @staticmethod
    def _fit(img, src, box):
        """Paste `src` scaled to fit `box`; return a function mapping src pixels -> img pixels."""
        bw, bh = box[2] - box[0], box[3] - box[1]
        s = min(bw / src.width, bh / src.height)
        sw, sh = max(1, int(src.width * s)), max(1, int(src.height * s))
        ox, oy = box[0] + (bw - sw) // 2, box[1] + (bh - sh) // 2
        img.alpha_composite(src.resize((sw, sh), Image.LANCZOS), (ox, oy))

        def to_px(x, y):
            return ox + x * s, oy + y * s
        to_px.back = lambda px, py: ((px - ox) / s, (py - oy) / s)
        return to_px

    def _route_points(self, snap, nav, P, to_px):
        if not nav or not nav.plan:
            pts = []
        else:
            pts = []
            for t in nav.plan:
                home, hx, hy = worldmap.home_of(self.world, t["from_area"])
                if home is None:
                    continue
                wpt = self.world.to_world(home, *((t["from_x"], t["from_y"]) if hx is None else (hx, hy)))
                pts.append(to_px(*P(*wpt)))
        if nav and nav.goal_xy:
            home, hx, hy = worldmap.home_of(self.world, nav.dest["area"])
            if home is not None:
                wpt = self.world.to_world(home, *(nav.goal_xy if hx is None else (hx, hy)))
                pts.append(to_px(*P(*wpt)))
        return pts

    def _area_only(self, img, snap, area_map_img, box):
        w_m, h_m = snap.size[0] * 10, snap.size[1] * 10
        src = area_map_img if area_map_img is not None else Image.new("RGBA", (w_m * 3, h_m * 3), (30, 38, 46, 255))
        ppx = src.width / w_m                       # source pixels per metre
        to_px = self._fit(img, src, box)
        d = ImageDraw.Draw(img)
        pois = self.store.area_pois(snap.area)
        hits = []
        for p in display_pois(pois):
            if p["kind"] != "pin":
                continue
            x, y = to_px(p["x"] * ppx, (h_m - p["y"]) * ppx)
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=GOLD, outline=(0, 0, 0, 255))
            if self.pin_labels:
                _text(d, (x + 8, y), (p["name"] or "")[:30], 8, GOLD, anchor="lm")
            if p["name"]:
                hits.append((x, y, {"kind": "pin", "area": snap.area, "name": p["name"], "x": p["x"], "y": p["y"]}))
        area = snap.area

        def spot(fx, fy):
            sx, sy = to_px.back(fx, fy)
            x, y = sx / ppx, h_m - sy / ppx
            return (area, x, y) if 0 <= x <= w_m and 0 <= y <= h_m else (None, None, None)
        self.clickable = {"box": box, "hits": hits, "spot": spot}
        return to_px(snap.pos[0] * ppx, (h_m - snap.pos[1]) * ppx)
