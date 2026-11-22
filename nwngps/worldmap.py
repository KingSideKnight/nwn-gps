"""World map: recorded areas stitched together by their edge transitions.

Two areas are placed side by side when a transition leaves one near an edge and
arrives near the opposite edge of the other (north->south, east->west, ...); the
areas are made to abut exactly and are offset along the shared edge by the
transition points. Areas reached through doors (interiors) can't be placed
geographically; they are attached as markers at their door in the parent area.

World coordinates: metres, x east, y north. Each area has an origin (its SW corner).
"""
import math
from collections import deque
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

EXIT_EDGE = 20.0     # metres: an exit this close to an edge counts as an edge exit
ENTRY_EDGE = 25.0    # entry waypoints are often placed further in
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def edge_of(x, y, w_m, h_m, limit):
    d = {"W": x, "E": w_m - x, "S": y, "N": h_m - y}
    k = min(d, key=d.get)
    return k if d[k] <= limit else None


@dataclass
class World:
    origin: dict = field(default_factory=dict)        # area -> (x, y) of its SW corner
    size: dict = field(default_factory=dict)          # area -> (w_m, h_m)
    cluster: dict = field(default_factory=dict)       # area -> cluster id
    interiors: list = field(default_factory=list)     # (parent area, x, y, interior area)

    def to_world(self, area, x, y):
        o = self.origin.get(area)
        return (o[0] + x, o[1] + y) if o else None

    def bounds(self, cid):
        xs, ys = [], []
        for a, c in self.cluster.items():
            if c == cid:
                (ox, oy), (w, h) = self.origin[a], self.size[a]
                xs += [ox, ox + w]
                ys += [oy, oy + h]
        return min(xs), min(ys), max(xs), max(ys)


def build(store, maps=None):
    """`maps` (a maps.Maps) lets us tell interiors from exteriors by their tileset; only
    exterior<->exterior edge crossings are placed geographically (stairs in a building can
    sit on its edges too)."""
    areas = {r["resref"]: r for r in store.db.execute("SELECT * FROM areas")}
    size = {a: (r["width"] * 10, r["height"] * 10) for a, r in areas.items() if r["width"] and r["height"]}
    interior = {a: (maps.is_interior(r["tileset"]) if maps else None) for a, r in areas.items()}
    geo = {}          # area -> [(neighbour, own_origin -> neighbour_origin offset)]
    door_links = []
    for t in store.transitions(include_unconfirmed=True):
        a, b = t["from_area"], t["to_area"]
        if a not in size or b not in size or a == b:
            continue
        (wa, ha), (wb, hb) = size[a], size[b]
        ea = edge_of(t["from_x"], t["from_y"], wa, ha, EXIT_EDGE)
        eb = edge_of(t["to_x"], t["to_y"], wb, hb, ENTRY_EDGE)
        if ea and eb == OPPOSITE[ea] and not interior.get(a) and not interior.get(b):
            if ea == "N":
                off = (t["from_x"] - t["to_x"], ha)
            elif ea == "S":
                off = (t["from_x"] - t["to_x"], -hb)
            elif ea == "E":
                off = (wa, t["from_y"] - t["to_y"])
            else:
                off = (-wb, t["from_y"] - t["to_y"])
            geo.setdefault(a, []).append((b, off))
            geo.setdefault(b, []).append((a, (-off[0], -off[1])))
        else:
            door_links.append(t)
    w = World(size=size)
    cid = 0
    # place biggest components first so cluster 0 is the main map
    for start in sorted(geo, key=lambda a: -len(geo[a])):
        if start in w.origin:
            continue
        w.origin[start], w.cluster[start] = (0.0, 0.0), cid
        q = deque([start])
        while q:
            a = q.popleft()
            for b, (dx, dy) in geo.get(a, []):
                if b not in w.origin:
                    w.origin[b] = (w.origin[a][0] + dx, w.origin[a][1] + dy)
                    w.cluster[b] = cid
                    q.append(b)
        cid += 1
    # interiors: attach each unplaced area to the first placed area that leads into it
    for t in door_links:
        a, b = t["from_area"], t["to_area"]
        if a in w.origin and b not in w.origin and not any(i[3] == b for i in w.interiors):
            w.interiors.append((a, t["from_x"], t["from_y"], b))
    # second level: interiors of interiors attach at their parent's door position
    changed = True
    while changed:
        changed = False
        placed_int = {i[3]: i for i in w.interiors}
        for t in door_links:
            a, b = t["from_area"], t["to_area"]
            if a in placed_int and b not in w.origin and b not in placed_int:
                p = placed_int[a]
                w.interiors.append((p[0], p[1], p[2], b))
                changed = True
    return w


def home_of(world, area):
    """(placed area, x, y) to show for `area`: itself if placed, else its door in the parent."""
    if area in world.origin:
        return area, None, None
    for parent, x, y, inner in world.interiors:
        if inner == area:
            return parent, x, y
    return None, None, None


def short_name(name):
    """'Cordor (The Walled City) Cultural District' -> 'Cultural District'."""
    return name.split(") ")[-1] if ") " in name else name


def _font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(world, store, maps, cid, ppm=1.6, margin=40):
    """Image of one cluster at `ppm` pixels per metre. Returns (image, world->pixel function)."""
    x0, y0, x1, y1 = world.bounds(cid)
    W = int((x1 - x0) * ppm) + 2 * margin
    H = int((y1 - y0) * ppm) + 2 * margin
    img = Image.new("RGBA", (W, H), (14, 18, 22, 255))
    d = ImageDraw.Draw(img)

    def P(wx, wy):
        return (margin + (wx - x0) * ppm, margin + (y1 - wy) * ppm)

    names = []
    for a, c in world.cluster.items():
        if c != cid:
            continue
        (ox, oy), (w_m, h_m) = world.origin[a], world.size[a]
        left, top = P(ox, oy + h_m)
        right, bottom = P(ox + w_m, oy)
        rec = store.tiles(a)
        if rec and maps:
            tileset, tw, th, tiles = rec
            art = maps.image(tileset, tw, th, tiles).resize((max(1, round(right - left)), max(1, round(bottom - top))),
                                                           Image.LANCZOS)
            img.alpha_composite(art, (round(left), round(top)))
        else:
            d.rectangle((left, top, right, bottom), fill=(30, 38, 46, 255))
            d.text(((left + right) / 2, (top + bottom) / 2 + 16), "map appears after your next visit",
                   font=_font(11), fill=(110, 122, 132, 255), anchor="mm")
        d.rectangle((left, top, right, bottom), outline=(90, 110, 125, 255), width=2)
        names.append(((left + right) / 2, top + 14, short_name(store.area_name(a))))
    labelled = set()
    for parent, x, y, inner in world.interiors:
        if world.cluster.get(parent) != cid or (parent, round(x), round(y)) in labelled:
            continue          # one label per door (deeper floors share their building's door)
        labelled.add((parent, round(x), round(y)))
        px, py = P(*world.to_world(parent, x, y))
        d.rectangle((px - 4, py - 4, px + 4, py + 4), fill=(242, 201, 76, 255), outline=(0, 0, 0, 255))
        label = short_name(store.area_name(inner))
        f = _font(11)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            d.text((px + 7 + dx, py + dy), label, font=f, fill=(0, 0, 0, 255), anchor="lm")
        d.text((px + 7, py), label, font=f, fill=(242, 201, 76, 255), anchor="lm")
    f = _font(14, True)
    for cx, ty, name in names:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
            d.text((cx + dx, ty + dy), name, font=f, fill=(0, 0, 0, 255), anchor="mt")
        d.text((cx, ty), name, font=f, fill=(232, 238, 242, 255), anchor="mt")
    return img, P
