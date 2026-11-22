"""Full-screen map (Ctrl+Shift+M): the stitched world map around you, with your position,
the route across areas and the destination. Falls back to the current area's own map when
that area isn't linked into the world map yet. Drawn at reduced resolution; the DLL scales
it to the game window on the GPU."""
import math

from PIL import Image, ImageDraw

from . import worldmap
from .panel import _arrow, _dashed, display_pois, font

BG = (10, 13, 16, 225)
FG, DIM, ROUTE, ME, GOLD = (232, 238, 242, 255), (125, 138, 148, 255), (76, 217, 100, 255), \
    (63, 193, 255, 255), (242, 201, 76, 255)
HEADER, FOOTER, PAD = 56, 34, 24


def frame_size(view_w, view_h, max_w=1600):
    """Render size with the game window's aspect ratio (the DLL scales it up)."""
    if not view_w or not view_h:
        return 1600, 900
    s = min(1.0, max_w / view_w)
    return max(640, int(view_w * s)), max(360, int(view_h * s))


def _text(d, xy, s, size, color, bold=False, anchor="la"):
    d.text(xy, s, font=font(size, bold), fill=color, anchor=anchor)   # font() sizes are SS-scaled


class FullMap:
    def __init__(self, store, maps):
        self.store, self.maps = store, maps
        self.world, self.cache = None, {}

    def rebuild(self):
        """Call when the database may have changed (area change)."""
        self.world = worldmap.build(self.store, self.maps)
        self.cache = {}

    def _cluster_img(self, cid):
        if cid not in self.cache:
            self.cache[cid] = worldmap.render(self.world, self.store, self.maps, cid, ppm=1.6)
        return self.cache[cid]

    def render(self, size, snap, g, nav, area_map_img):
        W, H = size
        img = Image.new("RGBA", (W, H), BG)
        d = ImageDraw.Draw(img)
        if self.world is None:
            self.rebuild()
        home, hx, hy = worldmap.home_of(self.world, snap.area) if snap.area else (None, None, None)
        box = (PAD, HEADER, W - PAD, H - FOOTER)
        if home is not None:
            cid = self.world.cluster[home]
            src, P = self._cluster_img(cid)
            title = "World map"
            here = self.world.to_world(home, *(snap.pos[:2] if hx is None else (hx, hy)))
            to_px = self._fit(img, src, box)
            me = to_px(*P(*here))
            route = self._route_points(snap, nav, P, to_px)
            inside = None if hx is None else snap.area_name
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
        _arrow(d, me[0] / 2, me[1] / 2, 9, math.degrees(math.atan2(fx, fy)), ME)
        # header / footer
        _text(d, (PAD, 16), title, 13, FG, bold=True)
        where = snap.area_name or ""
        if inside:
            where += "  (inside - shown at its door)"
        _text(d, (W - PAD, 18), where[:90], 9, DIM, anchor="ra")
        if g:
            _text(d, (PAD, H - 12), f"To {g.dest_name}: {g.line1}"[:140], 9, FG, anchor="ls")
        _text(d, (W - PAD, H - 12), "Ctrl+Shift+M  close map", 9, DIM, anchor="rs")
        return img

    @staticmethod
    def _fit(img, src, box):
        """Paste `src` scaled to fit `box`; return a function mapping src pixels -> img pixels."""
        bw, bh = box[2] - box[0], box[3] - box[1]
        s = min(bw / src.width, bh / src.height)
        sw, sh = max(1, int(src.width * s)), max(1, int(src.height * s))
        ox, oy = box[0] + (bw - sw) // 2, box[1] + (bh - sh) // 2
        img.alpha_composite(src.resize((sw, sh), Image.LANCZOS), (ox, oy))
        return lambda x, y: (ox + x * s, oy + y * s)

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
        pois = self.store.db.execute("SELECT kind,name,x,y FROM pois WHERE area=?", (snap.area,)).fetchall()
        for p in display_pois(pois):
            if p["kind"] != "pin":
                continue
            x, y = to_px(p["x"] * ppx, (h_m - p["y"]) * ppx)
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=GOLD, outline=(0, 0, 0, 255))
            _text(d, (x + 8, y), (p["name"] or "")[:30], 8, GOLD, anchor="lm")
        return to_px(snap.pos[0] * ppx, (h_m - snap.pos[1]) * ppx)
