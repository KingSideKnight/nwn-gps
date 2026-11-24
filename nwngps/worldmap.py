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

CONFLICT = 15.0      # metres: a link that would put an already-placed area this far off disagrees
EXIT_EDGE = 20.0     # metres: an exit this close to an edge counts as an edge exit
ENTRY_EDGE = 25.0    # entry waypoints are often placed further in
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
OVERLAP_TOL = 2.0    # metres: areas overlapping less than this (rounding, waypoints) are fine
MIN_SHARED = 10.0    # metres of common edge two joined areas keep when one is slid along it


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
    conflicts: list = field(default_factory=list)     # (area, neighbour, metres off): links that disagree
    slid: dict = field(default_factory=dict)          # area -> metres moved along its edge to clear an overlap
    links: dict = field(default_factory=dict)         # (a, b) sorted -> (a, (x, y), b, (x, y)): where a join crosses
    moved: dict = field(default_factory=dict)         # area -> (dx, dy) its branch was moved to clear an overlap
    stretched: list = field(default_factory=list)     # (a, b) joins no longer side by side: drawn as a line
    overlaps: list = field(default_factory=list)      # (a, b) overlaps nothing could clear (shouldn't happen)

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
    size = {a: (r["width"] * 10, r["height"] * 10) for a, r in areas.items()
            if isinstance(r["width"], int) and isinstance(r["height"], int)
            and 1 <= r["width"] <= 64 and 1 <= r["height"] <= 64}
    interior = {a: (maps.is_interior(r["tileset"]) if maps else None) for a, r in areas.items()}
    geo = {}          # area -> [(neighbour, own_origin -> neighbour_origin offset, axis it may slide on)]
    door_links = []
    joins = {}
    # Only walk/portal links say where areas are. Untrusted jumps and anything to do with dying
    # are left out entirely (a spell cast at a map edge must not glue two areas together).
    # Most-used links first, so one odd link can't outvote a well-trodden one.
    links = sorted(store.transitions(include_unconfirmed=True), key=lambda t: -(t["count"] or 1))
    for t in links:
        a, b = t["from_area"], t["to_area"]
        kind = t["kind"] or "walk"
        if a not in size or b not in size or a == b or kind in ("death", "respawn"):
            continue
        if kind == "jump":
            if t["confirmed"]:
                door_links.append(t)       # a trusted portal-like jump: a marker, never geography
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
            axis = "x" if ea in "NS" else "y"        # areas joined N/S can slide east-west, and vice versa
            geo.setdefault(a, []).append((b, off, axis))
            geo.setdefault(b, []).append((a, (-off[0], -off[1]), axis))
            joins.setdefault(tuple(sorted((a, b))), (a, (t["from_x"], t["from_y"]), b, (t["to_x"], t["to_y"])))
        else:
            door_links.append(t)
    w = World(size=size, links=joins)
    cid = 0
    # place biggest components first so cluster 0 is the main map
    for start in sorted(geo, key=lambda a: -len(geo[a])):
        if start in w.origin:
            continue
        w.origin[start], w.cluster[start] = (0.0, 0.0), cid
        q = deque([start])
        while q:
            a = q.popleft()
            for b, (dx, dy), _axis in geo.get(a, []):
                want = (w.origin[a][0] + dx, w.origin[a][1] + dy)
                if b not in w.origin:
                    w.origin[b] = want
                    w.cluster[b] = cid
                    q.append(b)
                else:
                    off = math.hypot(w.origin[b][0] - want[0], w.origin[b][1] - want[1])
                    if off > CONFLICT and a < b:      # each pair once
                        w.conflicts.append((a, b, round(off, 1)))
        _settle(w, geo, cid)
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


def overlap(world, a, b):
    """(x, y) metres by which two placed areas' rectangles overlap (<= 0: they don't)."""
    (ax, ay), (aw, ah) = world.origin[a], world.size[a]
    (bx, by), (bw, bh) = world.origin[b], world.size[b]
    return min(ax + aw, bx + bw) - max(ax, bx), min(ay + ah, by + bh) - max(ay, by)


def _settle(w, geo, cid):
    """Arrival waypoints are often well along the edge from the exit (Cordor Frontier -> Bramble
    Woods: 35 m), so lining links up exactly can stack areas on top of each other. An area whose
    joins all run along one axis (e.g. only an east edge) can slide along it without breaking
    any join: slide it the least distance that clears the overlap, keeping MIN_SHARED metres of
    every shared edge.

    The world isn't flat, though: Ansrivarr Pond -> Burial Grounds runs south off a pond west of
    Southern Entrance, whose south neighbour Earthkin Village is wide enough to sit under both.
    No slide clears that, so whatever still overlaps is pulled apart by `_separate`, and every
    join whose areas no longer sit side by side is listed in `stretched` (drawn as a line)."""
    members = [a for a, c in w.cluster.items() if c == cid]
    for _ in range(len(members)):
        moved = False
        for a, b in _overlapping(w, members):
            if not _hit(w, a, b):
                continue                  # an earlier slide in this pass cleared it
            # move the less-connected one (a dead end before a crossroads), then the smaller
            for mover, other in _movers(w, geo, a, b):
                if _slide(w, geo, members, mover, other):
                    moved = True
                    break
        if not moved:
            break
    _separate(w, geo, members)
    for key, (a, _, b, _) in w.links.items():
        if w.cluster.get(a) == cid and w.cluster.get(b) == cid and not _side_by_side(w, a, b):
            w.stretched.append(key)


def _hit(w, a, b):
    return all(v > OVERLAP_TOL for v in overlap(w, a, b))


def _box(w, a, dx=0.0, dy=0.0):
    (x, y), (bw, bh) = w.origin[a], w.size[a]
    return x + dx, y + dy, x + dx + bw, y + dy + bh


def _boxes_hit(p, q):
    return min(p[2], q[2]) - max(p[0], q[0]) > OVERLAP_TOL and min(p[3], q[3]) - max(p[1], q[1]) > OVERLAP_TOL


class _Grid:
    """Boxes bucketed by 160 m cells, so finding what overlaps what doesn't compare every pair
    (3,888 areas: 7.5 million pairs)."""
    CELL = 160.0

    def __init__(self, boxes):
        self.boxes, self.cells = boxes, {}
        for k, b in boxes.items():
            for c in self._cells(b):
                self.cells.setdefault(c, []).append(k)

    def _cells(self, b):
        f = lambda v: int(math.floor(v / self.CELL))
        return [(i, j) for i in range(f(b[0]), f(b[2]) + 1) for j in range(f(b[1]), f(b[3]) + 1)]

    def hits(self, box):
        """Keys whose boxes overlap `box` by more than OVERLAP_TOL both ways."""
        return {k for c in self._cells(box) for k in self.cells.get(c, ()) if _boxes_hit(box, self.boxes[k])}


def _overlapping(w, members):
    """Overlapping pairs of `members`, in members order."""
    rank = {a: i for i, a in enumerate(members)}
    g = _Grid({a: _box(w, a) for a in members})
    pairs = {(a, b) if rank[a] < rank[b] else (b, a) for ks in g.cells.values() for i, a in enumerate(ks)
             for b in ks[i + 1:] if _hit(w, a, b)}
    return sorted(pairs, key=lambda p: (rank[p[0]], rank[p[1]]))


def _movers(w, geo, a, b):
    return sorted(((a, b), (b, a)), key=lambda p: (len({n for n, _, _ in geo.get(p[0], ())}),
                                                   w.size[p[0]][0] * w.size[p[0]][1]))


def _side_by_side(w, a, b):
    """Do two joined areas still touch along MIN_SHARED metres of edge?"""
    ox, oy = overlap(w, a, b)
    return min(ox, oy) >= -OVERLAP_TOL and max(ox, oy) >= MIN_SHARED


def _branch(geo, inside, start, anchor):
    """Areas reachable from `start` without using its join to `anchor`; None if that join isn't
    the only way between them (a loop: moving one side would tear other joins)."""
    seen, q = {start}, deque([start])
    while q:
        a = q.popleft()
        for n, _, _ in geo.get(a, ()):
            if n not in inside or n in seen or (a == start and n == anchor):
                continue
            if n == anchor:
                return None
            seen.add(n)
            q.append(n)
    return seen


def _separate(w, geo, members):
    """Clear overlaps no slide could: move the smallest branch that hangs off one join (a dead end,
    or a dead-end chain) the shortest distance that puts it clear of everything, preferring to move
    it along that join's edge so it stays on the same side of its neighbour. Only that one join is
    stretched. An overlap inside a loop (no such branch) moves one area by itself."""
    inside, given_up = set(members), set()
    for _ in range(len(members)):
        pairs = [p for p in _overlapping(w, members) if p not in given_up]
        if not pairs:
            return
        a, b = pairs[0]
        options = []
        for mover, other in _movers(w, geo, a, b):
            for anchor, _, axis in geo.get(mover, ()):
                part = _branch(geo, inside, mover, anchor) if anchor in inside else None
                if part and other not in part and anchor not in part:
                    options.append(((0, len(part)), mover, part, axis))
            # last resort, inside a loop of joins that disagree: move the one area by itself
            joined = geo.get(mover) or [(None, None, "x")]
            options.append(((1, 0), mover, {mover}, joined[0][2]))
        best = None          # fewest areas moved, then the shortest move (along the join counts less)
        for rank, mover, part, axis in options:
            prefer = 0 if axis == "x" else 1
            shift = _free_shift(w, part, [m for m in members if m not in part], prefer)
            if shift:
                cost = abs(shift[prefer]) + 1.5 * abs(shift[1 - prefer])
                if best is None or (rank, cost) < best[0]:
                    best = ((rank, cost), mover, part, shift)
        if best is None:
            given_up.add((a, b))
            w.overlaps.append((a, b))
            continue
        _, mover, part, (dx, dy) = best
        for p in part:
            w.origin[p] = (w.origin[p][0] + dx, w.origin[p][1] + dy)
        old = w.moved.get(mover, (0.0, 0.0))
        w.moved[mover] = (old[0] + dx, old[1] + dy)


def _free_shift(w, part, rest, prefer):
    """Smallest (dx, dy) along one axis that leaves every area of `part` clear of every one of
    `rest`; moves along axis `prefer` count a third less. None if there is none."""
    fixed = _Grid({r: _box(w, r) for r in rest})
    cands = set()
    for s in part:
        sb = _box(w, s)
        for rb in fixed.boxes.values():
            for i in (0, 1):
                cands.add((i, rb[i + 2] - sb[i]))      # just past its far side
                cands.add((i, rb[i] - sb[i + 2]))      # just before its near side
    for i, d in sorted(cands, key=lambda c: abs(c[1]) * (1.0 if c[0] == prefer else 1.5)):
        dx, dy = (d, 0.0) if i == 0 else (0.0, d)
        if abs(d) > OVERLAP_TOL and not any(fixed.hits(_box(w, s, dx, dy)) for s in part):
            return dx, dy
    return None


def _slide(w, geo, members, mover, other):
    axes = {axis for _, _, axis in geo[mover]}
    if len(axes) != 1:
        return False
    i = 0 if axes.pop() == "x" else 1
    lo, size = w.origin[mover][i], w.size[mover][i]
    olo, osize = w.origin[other][i], w.size[other][i]
    for shift in sorted((olo + osize - lo, olo - (lo + size)), key=abs):
        old = w.origin[mover]
        w.origin[mover] = (old[0] + shift, old[1]) if i == 0 else (old[0], old[1] + shift)
        clear = all(not all(v > OVERLAP_TOL for v in overlap(w, mover, m)) for m in members if m != mover)
        joined = all(overlap(w, mover, n)[i] >= MIN_SHARED for n, _, _ in geo[mover])
        if clear and joined:
            w.slid[mover] = w.slid.get(mover, 0.0) + shift
            return True
        w.origin[mover] = old
    return False


def draw_order(world, cid):
    """Areas of a cluster in drawing order: what's drawn later covers what's under it."""
    return [a for a, c in world.cluster.items() if c == cid]


def covered(world, order, area, wx, wy):
    """Is world point (wx, wy) of `area` under an area drawn after it?"""
    later = order[order.index(area) + 1:] if area in order else []
    for b in later:
        (bx, by), (bw, bh) = world.origin[b], world.size[b]
        if bx + 1 < wx < bx + bw - 1 and by + 1 < wy < by + bh - 1:
            return True
    return False


def area_at(world, cid, wx, wy):
    """The area of cluster `cid` drawn at world point (wx, wy) (the one on top), or None."""
    for a in reversed(draw_order(world, cid)):
        (ax, ay), (w, h) = world.origin[a], world.size[a]
        if ax <= wx <= ax + w and ay <= wy <= ay + h:
            return a
    return None


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


_art_cache = {}            # (area, layout saved at, w_px, h_px) -> scaled tile art (bounded LRU)
ART_CACHE_MAX = 96


def _area_art(store, maps, area, wpx, hpx):
    saved = store.db.execute("SELECT seen FROM area_tiles WHERE resref=?", (area,)).fetchone()
    key = (area, saved[0] if saved else None, wpx, hpx)       # a replaced layout gets new art
    if key in _art_cache:
        _art_cache[key] = _art_cache.pop(key)        # most recently used last
        return _art_cache[key]
    rec = store.tiles(area)
    art = None
    if rec and maps:
        tileset, tw, th, tiles = rec
        art = maps.image(tileset, tw, th, tiles).resize((wpx, hpx), Image.LANCZOS)
    if art is None:
        return None          # tiles not recorded yet (the recorder saves them shortly after you arrive)
    _art_cache[key] = art
    while len(_art_cache) > ART_CACHE_MAX:
        _art_cache.pop(next(iter(_art_cache)))
    return art


def render_view(world, store, maps, cid, view, out_w, out_h, pin_labels=True, hits=None):
    """Draw only the part of cluster `cid` inside `view` = (x0, y0, x1, y1) world metres, at
    out_w x out_h pixels. Cost depends on what's visible, not on how big the world is.
    hits: a list that gets (px, py, destination) for every marker drawn, for clicking.
    Returns (image, world->pixel function)."""
    vx0, vy0, vx1, vy1 = view
    ppm = min(out_w / (vx1 - vx0), out_h / (vy1 - vy0))
    ox = (out_w - (vx1 - vx0) * ppm) / 2
    oy = (out_h - (vy1 - vy0) * ppm) / 2
    img = Image.new("RGBA", (out_w, out_h), (14, 18, 22, 255))
    d = ImageDraw.Draw(img)

    def P(wx, wy):
        return (ox + (wx - vx0) * ppm, oy + (vy1 - wy) * ppm)

    names = []
    for a, c in world.cluster.items():
        if c != cid:
            continue
        (ax, ay), (w_m, h_m) = world.origin[a], world.size[a]
        if ax > vx1 or ax + w_m < vx0 or ay > vy1 or ay + h_m < vy0:
            continue                                  # not visible
        left, top = P(ax, ay + h_m)
        right, bottom = P(ax + w_m, ay)
        wpx, hpx = max(1, round(right - left)), max(1, round(bottom - top))
        art = _area_art(store, maps, a, wpx, hpx) if wpx * hpx < 16_000_000 else None
        if art is not None:
            img.alpha_composite(art, (round(left), round(top))) if left >= 0 and top >= 0 else \
                img.paste(art, (round(left), round(top)), art)
        else:
            d.rectangle((left, top, right, bottom), fill=(30, 38, 46, 255))
            d.text(((left + right) / 2, (top + bottom) / 2 + 16), "map appears after your next visit",
                   font=_font(11), fill=(110, 122, 132, 255), anchor="mm")
        d.rectangle((left, top, right, bottom), outline=(90, 110, 125, 255), width=2)
        names.append(((left + right) / 2, max(top + 14, 14), short_name(store.area_name(a))))
    _joins(d, world, cid, P)
    names = _place_names(d, names)
    _markers(d, world, store, cid, P, out_w, out_h, names, pin_labels, hits)
    _names(d, names)
    return img, P


GOLD = (242, 201, 76, 255)
PIN_NEAR_DOOR = 8.0      # metres: a pin this close to a building marker is that marker's label


def _label(d, x, y, text, taken, size=11):
    """Outlined gold label to the right of (x, y), unless it would overlap one already drawn."""
    f = _font(size)
    box = d.textbbox((x + 7, y), text, font=f, anchor="lm")
    box = (box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1)
    if any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in taken):
        return
    taken.append(box)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        d.text((x + 7 + dx, y + dy), text, font=f, fill=(0, 0, 0, 255), anchor="lm")
    d.text((x + 7, y), text, font=f, fill=GOLD, anchor="lm")


def _markers(d, world, store, cid, P, out_w, out_h, names, pin_labels=True, hits=None):
    """Building markers (squares, at the door) and the areas' map pins (dots) of cluster `cid`.
    Labels never overlap each other or the area names; dots are always drawn. pin_labels=False
    leaves out the pins' names (building names stay)."""
    from .panel import display_pois
    taken = [d.textbbox((cx, ty), name, font=_font(14, True), anchor="mt") for cx, ty, name in names]
    visible = lambda px, py: -20 <= px < out_w + 20 and -20 <= py < out_h + 20
    order = draw_order(world, cid)
    doors, labelled = {}, set()
    for parent, x, y, inner in world.interiors:
        if world.cluster.get(parent) != cid or (parent, round(x), round(y)) in labelled:
            continue          # one label per door (deeper floors share their building's door)
        labelled.add((parent, round(x), round(y)))
        doors.setdefault(parent, []).append((x, y))
        if covered(world, order, parent, *world.to_world(parent, x, y)):
            continue          # under an area drawn on top: its markers would bleed through
        px, py = P(*world.to_world(parent, x, y))
        if not visible(px, py):
            continue
        d.rectangle((px - 4, py - 4, px + 4, py + 4), fill=GOLD, outline=(0, 0, 0, 255))
        _label(d, px, py, short_name(store.area_name(inner)), taken)
        if hits is not None:
            hits.append((px, py, {"kind": "area", "area": inner, "name": store.area_name(inner),
                                  "x": None, "y": None}))
    for a, c in world.cluster.items():
        if c != cid:
            continue
        for p in display_pois(store.area_pois(a)):
            if p["kind"] != "pin" or not p["name"]:
                continue
            if any(math.hypot(p["x"] - x, p["y"] - y) <= PIN_NEAR_DOOR for x, y in doors.get(a, ())):
                continue      # the building marker there already says where it goes
            wx, wy = world.to_world(a, p["x"], p["y"])
            if covered(world, order, a, wx, wy):
                continue
            px, py = P(wx, wy)
            if not visible(px, py):
                continue
            d.ellipse((px - 4, py - 4, px + 4, py + 4), fill=GOLD, outline=(0, 0, 0, 255))
            if pin_labels:
                _label(d, px, py, p["name"], taken)
            if hits is not None:
                hits.append((px, py, {"kind": "pin", "area": a, "name": p["name"], "x": p["x"], "y": p["y"]}))


def join_lines(world, cid):
    """World-coordinate segments (exit, entry) for the joins of cluster `cid` whose areas were
    pulled apart, so the map still shows where one leads into the other."""
    out = []
    for key in world.stretched:
        a, pa, b, pb = world.links[key]
        if world.cluster.get(a) == cid:
            out.append((world.to_world(a, *pa), world.to_world(b, *pb)))
    return out


def _joins(d, world, cid, P, dash=6.0):
    for (ax, ay), (bx, by) in join_lines(world, cid):
        (x0, y0), (x1, y1) = P(ax, ay), P(bx, by)
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / dash))
        for i in range(0, n, 2):
            seg = (x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n,
                   x0 + (x1 - x0) * min(i + 1, n) / n, y0 + (y1 - y0) * min(i + 1, n) / n)
            d.line(seg, fill=(0, 0, 0, 255), width=5)
            d.line(seg, fill=(232, 238, 242, 255), width=3)
        for x, y in ((x0, y0), (x1, y1)):
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(232, 238, 242, 255), outline=(0, 0, 0, 255))


def _place_names(d, names):
    """Move an area name down a line or two if it would run into a name already placed (areas
    side by side with long names)."""
    f, cells, out, cell = _font(14, True), {}, [], 128
    span = lambda b: [(i, j) for i in range(int(b[0] // cell), int(b[2] // cell) + 1)
                      for j in range(int(b[1] // cell), int(b[3] // cell) + 1)]
    for cx, ty, name in names:
        for y in (ty, ty + 18, ty + 36):
            box = d.textbbox((cx, y), name, font=f, anchor="mt")
            if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]
                       for c in span(box) for b in cells.get(c, ())):
                break
        for c in span(box):
            cells.setdefault(c, []).append(box)
        out.append((cx, y, name))
    return out


def _names(d, names):
    f = _font(14, True)
    for cx, ty, name in names:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
            d.text((cx + dx, ty + dy), name, font=f, fill=(0, 0, 0, 255), anchor="mt")
        d.text((cx, ty), name, font=f, fill=(232, 238, 242, 255), anchor="mt")


def render(world, store, maps, cid, ppm=1.6, margin=40):
    """Whole cluster as one image (for `cli worldmap` export)."""
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
    _joins(d, world, cid, P)
    names = _place_names(d, names)
    _markers(d, world, store, cid, P, W, H, names)
    _names(d, names)
    return img, P
