"""Walking paths inside an area, from its tiles' walkmeshes.

Every tile model has a walkmesh (.wok, ASCII): triangles tagged with a surface material, and the
game's surfacemat.2da says which materials you can walk on. Laid out like the tile art (centre of
tile i at ((i % w) * 10 + 5, (i // w) * 10 + 5), turned 90 degrees x orientation counter-clockwise),
they give a 0.5 m walkable grid of the area. A* on that grid, then straightened into a few turns,
is the way on foot to the next exit.

Paths(log).route(area, pos, target) -> Walk (the rest of the path from where you are) or None
(no walkmesh / no path / still searching: show a straight line as before). The search runs on its
own thread; grids are cached next to the area map pictures.

Server content is untrusted: walkmeshes and tables are size- and count-capped, and anything odd
makes that tile (or the whole area) fall back to straight lines, never an error.
"""
import heapq
import math
import os
import re
import threading
import time

try:
    import numpy as np
except ImportError:                    # running from source without numpy: straight lines only
    np = None

from .maps import MAP_DIR, MAX_AREA_TILES, MAX_SET_BYTES, Maps

CELL = 0.5                             # metres per grid cell
TILE_CELLS = int(10 / CELL)
WOK, SURFACEMAT = 2016, 2017           # resource types
MAX_WOK_BYTES = 4 * 1024 * 1024
MAX_WOK_ITEMS = 50000                  # vertices / faces in one tile walkmesh (real ones: a few hundred)
MAX_2DA_BYTES = 256 * 1024
MAX_EXPANSIONS = 600000                # A* gives up after this many cells (a huge area with no way through)
SNAP_START = 3.0                       # metres: you're always on the walkmesh, give or take a cell
SNAP_GOAL = 10.0                       # exits are recorded where you stood, often past the walkable edge
FAR_PENALTY = 1000.0                   # per cell short of an unreachable goal: get as close as you can
STRAY = 5.0                            # metres off the path before searching again
LOST = 15.0                            # this far off, the old path is no help: straight line until the new one
RETRY_AFTER = 10.0                     # seconds before trying again after "no path"
GRID_VERSION = 1                       # bump when the grid format or rules change (new cache files)
DIST_VERSION = 1                       # ... and the walking-distance tables
GRID_STRETCH = 1.04                    # 8-direction grid steps vs a straight line: about 4% longer on average
HERE_MOVED = 10.0                      # metres you move before the distances from you are worked out again
# A background search hands the interpreter back every 512 cells: otherwise each database call the game
# loop makes can wait a whole Windows timer tick (15.6 ms) to get it back.
YIELD_EVERY = 511
FILL_PAUSE = 0.02                      # seconds between background distance searches (leave the CPU to the game)


def available():
    return np is not None


# ---- parsing (untrusted) --------------------------------------------------------------------------
def walk_materials(data):
    """Set of walkable surface material ids from surfacemat.2da, or None if it can't be read."""
    if not data or len(data) > MAX_2DA_BYTES:
        return None
    lines = [ln.split() for ln in data.decode("latin-1").splitlines()]
    lines = [p for p in lines if p]
    if not lines or lines[0][0] != "2DA":
        return None
    header = next((p for p in lines[1:] if not p[0].isdigit()), None)
    if not header or "Walk" not in header:
        return None
    col = header.index("Walk") + 1                     # rows start with their index
    out = set()
    for p in lines:
        if p[0].isdigit() and len(p) > col and p[col] == "1":
            out.add(int(p[0]))
    return out


def parse_wok(data):
    """Triangles of a tile walkmesh: (x0, y0, x1, y1, x2, y2, material) in tile-local metres.
    Raises ValueError for anything that isn't a sane walkmesh."""
    if len(data) > MAX_WOK_BYTES:
        raise ValueError("walkmesh too large")
    lines = data.decode("latin-1").splitlines()
    verts, out, i = None, [], 0
    pos, turn = (0.0, 0.0), 0.0                        # the node's offset and turn about z
    while i < len(lines):
        p = lines[i].split()
        key = p[0].lower() if p else ""
        if key == "node":
            pos, turn = (0.0, 0.0), 0.0
        elif key == "position" and len(p) >= 3:
            pos = (float(p[1]), float(p[2]))
        elif key == "orientation" and len(p) >= 5:
            ax, ay, az, angle = map(float, p[1:5])
            if angle and abs(ax) < 1e-3 and abs(ay) < 1e-3 and abs(az) > 1e-3:
                turn = angle if az > 0 else -angle     # anything but a turn about z: ignored
        elif key in ("verts", "faces") and len(p) > 1:
            n = int(p[1])
            if not 0 <= n <= MAX_WOK_ITEMS or i + n >= len(lines) or len(out) + n > MAX_WOK_ITEMS:
                raise ValueError("bad walkmesh count")
            block = [lines[i + 1 + k].split() for k in range(n)]
            if key == "verts":
                c, s = math.cos(turn), math.sin(turn)
                verts = [(pos[0] + c * x - s * y, pos[1] + s * x + c * y)
                         for x, y in ((float(v[0]), float(v[1])) for v in block)]
            else:
                if verts is None:
                    raise ValueError("walkmesh faces before vertices")
                for f in block:
                    a, b, c_, mat = int(f[0]), int(f[1]), int(f[2]), int(f[7])
                    if not all(0 <= k < len(verts) for k in (a, b, c_)):
                        raise ValueError("walkmesh face points past its vertices")
                    pts = (*verts[a], *verts[b], *verts[c_])
                    if all(math.isfinite(v) and abs(v) <= 6.0 for v in pts):   # a tile is 10 m: +-5 plus slack
                        out.append((*pts, mat))
            i += n
        i += 1
    if verts is None:
        raise ValueError("walkmesh without vertices")
    return out


def tile_models(set_data):
    """{tile_id: model resref} from a tileset .set file."""
    if not set_data or len(set_data) > MAX_SET_BYTES:
        return {}
    out = {}
    for m in re.finditer(r"^\[TILE(\d+)\]\s*$(.*?)(?=^\[)", set_data.decode("latin-1"), re.S | re.M):
        model = re.search(r"^Model=(\S+)", m.group(2), re.M)
        if model:
            out[int(m.group(1))] = model.group(1).lower()
    return out


# ---- the grid --------------------------------------------------------------------------------------
def tile_mask(tris, walkable, orient):
    """TILE_CELLS x TILE_CELLS bool mask (row 0 = south) of one tile turned by `orient`: cells
    whose centre lies on a walkable triangle and on no unwalkable one."""
    n = TILE_CELLS
    walk = np.zeros((n, n), dtype=bool)
    block = np.zeros_like(walk)
    a = math.radians(90 * orient)
    ca, sa = math.cos(a), math.sin(a)
    for x0, y0, x1, y1, x2, y2, mat in tris:
        pts = [((5 + ca * x - sa * y) / CELL, (5 + sa * x + ca * y) / CELL) for x, y in ((x0, y0), (x1, y1), (x2, y2))]
        (ax, ay), (bx, by), (cx_, cy_) = pts
        gx0, gx1 = max(0, math.floor(min(ax, bx, cx_))), min(n - 1, math.ceil(max(ax, bx, cx_)))
        gy0, gy1 = max(0, math.floor(min(ay, by, cy_))), min(n - 1, math.ceil(max(ay, by, cy_)))
        if gx1 < gx0 or gy1 < gy0:
            continue
        px, py = np.meshgrid(np.arange(gx0, gx1 + 1) + 0.5, np.arange(gy0, gy1 + 1) + 0.5)

        def edge(ux, uy, vx, vy):
            return (vx - ux) * (py - uy) - (vy - uy) * (px - ux)
        e0, e1, e2 = edge(ax, ay, bx, by), edge(bx, by, cx_, cy_), edge(cx_, cy_, ax, ay)
        eps = 1e-9
        inside = ((e0 >= -eps) & (e1 >= -eps) & (e2 >= -eps)) | ((e0 <= eps) & (e1 <= eps) & (e2 <= eps))
        (walk if mat in walkable else block)[gy0:gy1 + 1, gx0:gx1 + 1] |= inside
    return walk & ~block


class Grids:
    """Walkable grids by area layout, built from a Resources and cached on disk."""

    def __init__(self, resources):
        self.res = resources
        self.walkable = walk_materials(resources.get("surfacemat", SURFACEMAT))
        self.models, self.woks, self.masks = {}, {}, {}

    @staticmethod
    def path(tileset, w, h, tiles):
        return MAP_DIR / f"{Maps.key(tileset, w, h, tiles)}.walk{GRID_VERSION}"

    def grid(self, tileset, w, h, tiles):
        """(H, W) bool array, row 0 = south, or None when the area has no usable walkmesh."""
        if self.walkable is None or not (isinstance(w, int) and isinstance(h, int)
                                         and 1 <= w <= MAX_AREA_TILES and 1 <= h <= MAX_AREA_TILES
                                         and len(tiles) == w * h):
            return None
        path = self.path(tileset, w, h, tiles)
        shape = (h * TILE_CELLS, w * TILE_CELLS)
        cached = load_grid(path, shape)
        if cached is not None:
            try:
                path.touch()                           # recently used: the cache pruning keeps it
            except OSError:
                pass
            return cached
        if tileset not in self.models:
            self.models[tileset] = tile_models(self.res.get(tileset, "set"))
        models = self.models[tileset]
        grid = np.zeros(shape, dtype=bool)
        found = 0
        for i, (tid, orient, _height) in enumerate(tiles):
            time.sleep(0)                      # let the game loop in (see YIELD_EVERY)
            mask = self.mask(models.get(tid), orient & 3)
            if mask is None:
                continue
            found += 1
            r, c = (i // w) * TILE_CELLS, (i % w) * TILE_CELLS
            grid[r:r + TILE_CELLS, c:c + TILE_CELLS] = mask
        if found * 2 < len(tiles):                     # mostly missing: paths would be nonsense
            return None
        save_grid(grid, path)
        return grid

    def mask(self, model, orient):
        if not model:
            return None
        if model not in self.woks:
            try:
                data = self.res.get(model, WOK)
                self.woks[model] = parse_wok(data) if data else None
            except (ValueError, IndexError):
                self.woks[model] = None
        if self.woks[model] is None:
            return None
        key = (model, orient)
        if key not in self.masks:
            self.masks[key] = tile_mask(self.woks[model], self.walkable, orient)
        return self.masks[key]


def save_grid(grid, path):
    h, w = grid.shape
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(h.to_bytes(4, "little") + w.to_bytes(4, "little") + np.packbits(grid).tobytes())
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def load_grid(path, shape):
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    h, w = int.from_bytes(raw[:4], "little"), int.from_bytes(raw[4:8], "little")
    if (h, w) != shape or len(raw) != 8 + (h * w + 7) // 8:
        return None
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8, offset=8), count=h * w)
    return bits.reshape(shape).astype(bool)


# ---- searching -------------------------------------------------------------------------------------
def cell_of(x, y):
    return int(math.floor(x / CELL)), int(math.floor(y / CELL))


def centre(c):
    return ((c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL)


def snap(grid, x, y, radius_m):
    """Nearest walkable cell to (x, y) within radius_m, or None."""
    H, W = grid.shape
    cx, cy = cell_of(x, y)
    r = int(math.ceil(radius_m / CELL))
    x0, x1, y0, y1 = max(0, cx - r), min(W, cx + r + 1), max(0, cy - r), min(H, cy + r + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    ys, xs = np.nonzero(grid[y0:y1, x0:x1])
    if not len(xs):
        return None
    d = (xs + x0 - cx) ** 2 + (ys + y0 - cy) ** 2
    k = int(np.argmin(d))
    if d[k] > r * r:
        return None
    return int(xs[k] + x0), int(ys[k] + y0)


def astar(grid, start, ends, toward=None, max_expansions=MAX_EXPANSIONS):
    """Cells from start to one of `ends` ({cell: extra cost of ending there}), 8 directions and
    never cutting a corner, or None. toward: the cell to aim the search at (one end, no extra
    cost); without it the search spreads evenly (any end will do)."""
    H, W = grid.shape
    Wp = W + 2                                         # a blocked border: no bounds checks
    free = np.pad(grid, 1).ravel().tolist()
    s = (start[1] + 1) * Wp + start[0] + 1
    goals = {(y + 1) * Wp + x + 1: extra for (x, y), extra in ends.items()}
    if not free[s] or not any(free[c] for c in goals):
        return None
    tx, ty = (toward[0] + 1, toward[1] + 1) if toward else (None, None)
    sq2 = math.sqrt(2)
    straight = (1, -1, Wp, -Wp)
    diagonal = ((Wp + 1, 1, Wp), (Wp - 1, -1, Wp), (-Wp + 1, 1, -Wp), (-Wp - 1, -1, -Wp))
    g = {s: 0.0}
    came = {}
    heap = [(0.0, s)]
    done = set()
    END = -1
    expanded = 0
    while heap:
        _, cur = heapq.heappop(heap)
        if cur == END:
            cur = came[END]
            out = [cur]
            while cur in came:
                cur = came[cur]
                out.append(cur)
            return [(i % Wp - 1, i // Wp - 1) for i in reversed(out)]
        if cur in done:
            continue
        done.add(cur)
        expanded += 1
        if expanded > max_expansions:
            return None
        if not expanded & YIELD_EVERY:
            time.sleep(0)                  # let the game loop in (see YIELD_EVERY)
        gc = g[cur]
        if cur in goals:
            ng = gc + goals[cur]
            if ng < g.get(END, 1e18):
                g[END], came[END] = ng, cur
                heapq.heappush(heap, (ng, END))
        steps = [(cur + o, 1.0) for o in straight if free[cur + o]]
        steps += [(cur + o, sq2) for o, ox, oy in diagonal if free[cur + o] and free[cur + ox] and free[cur + oy]]
        for nb, cost in steps:
            ng = gc + cost
            if ng < g.get(nb, 1e18):
                g[nb] = ng
                came[nb] = cur
                if tx is None:
                    h = 0.0
                else:                                  # octile distance: exact on an open grid
                    dx, dy = abs(nb % Wp - tx), abs(nb // Wp - ty)
                    h = max(dx, dy) + (sq2 - 1) * min(dx, dy)
                heapq.heappush(heap, (ng + h, nb))
    return None


def near_cells(grid, x, y, radius_m):
    """{cell: extra cost} of the walkable cells within radius_m of (x, y): ending further from it
    costs more than any detour, so the path ends as close to it as can be reached."""
    H, W = grid.shape
    fx, fy = x / CELL - 0.5, y / CELL - 0.5            # in cell-centre units
    r = radius_m / CELL
    out = {}
    for cy in range(max(0, int(fy - r)), min(H, int(fy + r) + 2)):
        for cx in range(max(0, int(fx - r)), min(W, int(fx + r) + 2)):
            d = math.hypot(cx - fx, cy - fy)
            if d <= r and grid[cy, cx]:
                out[(cx, cy)] = FAR_PENALTY * d
    return out


def line_clear(grid, a, b):
    """Is the straight line between cell centres a and b on walkable cells all the way?"""
    (ax, ay), (bx, by) = a, b
    n = int(max(abs(bx - ax), abs(by - ay)) * 4) + 1
    ts = np.linspace(0.0, 1.0, n + 1)
    xs = np.floor(ax + 0.5 + (bx - ax) * ts).astype(int)
    ys = np.floor(ay + 0.5 + (by - ay) * ts).astype(int)
    return bool(grid[ys, xs].all())


def straighten(grid, cells):
    """The few cells where the path has to turn (string pulling along the grid path)."""
    if len(cells) <= 2:
        return list(cells)
    out = [cells[0]]
    anchor, last = cells[0], cells[1]
    for c in cells[2:]:
        if not line_clear(grid, anchor, c):
            out.append(last)
            anchor = last
        last = c
    out.append(cells[-1])
    return out


def find_path(grid, start, goal):
    """[(x, y), ...] in metres from start to goal along walkable ground, or None. The path ends
    at the walkable spot nearest the goal, or if that can't be reached (a walled-off corner),
    as near the goal as you can get."""
    a = snap(grid, *start, SNAP_START)
    b = snap(grid, *goal, SNAP_GOAL)
    if a is None or b is None:
        return None
    cells = astar(grid, a, {b: 0.0}, toward=b)
    if cells is None:
        cells = astar(grid, a, near_cells(grid, *goal, SNAP_GOAL))
    if cells is None:
        return None
    turns = [centre(c) for c in straighten(grid, cells)[1:-1]]
    return [tuple(start)] + turns + [tuple(goal)]


def distances(grid, start, targets, max_expansions=MAX_EXPANSIONS):
    """{target: metres on foot, or None if there's no way} from start to each target (x, y),
    all from one search. Grid steps run a few percent longer than a straight line, so a leg
    counts as GRID_STRETCH shorter, and never shorter than the straight line itself."""
    out = {t: None for t in targets}
    a = snap(grid, *start, SNAP_START)
    if a is None:
        return out
    H, W = grid.shape
    Wp = W + 2
    want = {}
    for t in targets:
        b = snap(grid, *t, SNAP_GOAL)
        if b is not None:
            want.setdefault((b[1] + 1) * Wp + b[0] + 1, []).append((t, b))
    if not want:
        return out
    free = np.pad(grid, 1).ravel().tolist()
    s = (a[1] + 1) * Wp + a[0] + 1
    sq2 = math.sqrt(2)
    straight = (1, -1, Wp, -Wp)
    diagonal = ((Wp + 1, 1, Wp), (Wp - 1, -1, Wp), (-Wp + 1, 1, -Wp), (-Wp - 1, -1, -Wp))
    g = {s: 0.0}
    heap = [(0.0, s)]
    done = set()
    left = set(want)
    lead = math.dist(start, centre(a))
    while heap and left and len(done) < max_expansions:
        cost, cur = heapq.heappop(heap)
        if cur in done:
            continue
        done.add(cur)
        if not len(done) & YIELD_EVERY:
            time.sleep(0)                  # let the game loop in (see YIELD_EVERY)
        if cur in left:
            left.discard(cur)
            for t, b in want[cur]:
                metres = lead + cost * CELL / GRID_STRETCH + math.dist(centre(b), t)
                out[t] = max(math.dist(start, t), metres)
        steps = [(cur + o, 1.0) for o in straight if free[cur + o]]
        steps += [(cur + o, sq2) for o, ox, oy in diagonal if free[cur + o] and free[cur + ox] and free[cur + oy]]
        for nb, c in steps:
            ng = cost + c
            if ng < g.get(nb, 1e18):
                g[nb] = ng
                heapq.heappush(heap, (ng, nb))
    return out


def key_xy(xy):
    return (round(float(xy[0]), 1), round(float(xy[1]), 1))


def dist_path(tileset, w, h, tiles):
    return MAP_DIR / f"{Maps.key(tileset, w, h, tiles)}.walkdist{DIST_VERSION}"


def load_dists(path):
    """{(from, to): metres or None} saved for one layout (our own cache; damaged = empty)."""
    import json
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for k, v in raw.items():
            a, b = k.split("|")
            fx, fy = map(float, a.split(","))
            tx, ty = map(float, b.split(","))
            if v is not None and not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
                continue
            out[((fx, fy), (tx, ty))] = None if v is None else float(v)
        return out
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def save_dists(table, path):
    import json
    data = {f"{a[0]},{a[1]}|{b[0]},{b[1]}": (None if v is None else round(v, 1)) for (a, b), v in table.items()}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


# ---- following a path ------------------------------------------------------------------------------
class Walk:
    """Where you are on a path: the rest of it from you, how far that is, and where to head now."""

    def __init__(self, points, length, aim, off):
        self.points, self.length, self.aim, self.off = points, length, aim, off


def _project(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    q = (ax + t * dx, ay + t * dy)
    return q, math.dist(p, q)


class Route:
    def __init__(self, area, target, points):
        self.area, self.target, self.points = area, target, points
        self.seg = 0                                   # the segment you're on (only moves forward)

    def follow(self, pos):
        pts = self.points
        best = None
        for i in range(self.seg, len(pts) - 1):
            _q, d = _project(pos, pts[i], pts[i + 1])
            if best is None or d < best[1] - 1e-6:
                best = (i, d)
        if best is None:
            return Walk([tuple(pos), pts[-1]], math.dist(pos, pts[-1]), pts[-1], 0.0)
        i, off = best
        self.seg = i
        rest = [tuple(pos)] + pts[i + 1:]
        length = sum(math.dist(a, b) for a, b in zip(rest, rest[1:]))
        aim = rest[1]
        if math.dist(pos, aim) < 1.5 and len(rest) > 2:
            aim = rest[2]                              # at the corner already: head for the next one
        return Walk(rest, length, aim, off)


def _same(a, b):
    return a is not None and b is not None and abs(a[0] - b[0]) < 0.05 and abs(a[1] - b[1]) < 0.05


class Paths:
    """Paths in the area you're in, searched on a background thread."""

    def __init__(self, log=print, make_resources=None, fill=True):
        self.log = log
        self.make_resources = make_resources
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.layout, self.host = None, None            # (area, (tileset, w, h, tiles)) of the area you're in
        self.want = None                               # (area, start, target): the search to run next
        self.route = None                              # the last path found
        self.failed = None                             # (area, start, target, when) of the last "no path"
        self.thread = None
        self.fill = fill                               # False: only read tables another GPS window saved
        self.dists = {}                                # area -> {(from, to): metres or None (no way)}
        self.dists_for = {}                            # area -> layout those distances belong to
        self.jobs = []                                 # [(area, layout, sources, targets)], most wanted first
        self.here = None                               # (area, pos, {target: metres or None}) from you
        self.here_want = None                          # (area, pos, targets): distances from you to work out

    def set_area(self, area, layout, host=None):
        """The area you're in now and its tile layout (None: unknown, straight lines)."""
        if not available():
            return
        with self.lock:
            self.layout = (area, layout) if layout else None
            self.host = host
            self.want = None
        self.start()
        self.wake.set()

    def walk(self, area, pos, target):
        """The way on foot from pos to target in `area`, or None (straight line)."""
        if not available() or target is None or pos is None:
            return None
        pos = (float(pos[0]), float(pos[1]))
        target = (float(target[0]), float(target[1]))
        with self.lock:
            r = self.route
            here = self.layout and self.layout[0] == area
            if not here:
                return None
            w = r.follow(pos) if r and r.area == area and _same(r.target, target) else None
            if w is None or w.off > STRAY:
                self._ask(area, pos, target)
        if w is None or w.off > LOST:
            return None
        return w

    # ---- walking distances between exits, for choosing routes --------------------------------------
    def cost(self, area, frm, to):
        """Metres on foot from point frm to point to in `area`: a number, math.inf (no way there),
        or None (not known yet: use a straight line)."""
        with self.lock:
            table = self.dists.get(area)
            if table is None:
                return None
            k = (key_xy(frm), key_xy(to))
            if k not in table:
                return None
            v = table[k]
        return math.inf if v is None else v

    def here_cost(self, area, to):
        """Like cost(), from where you were when the distances from you were last worked out."""
        with self.lock:
            h = self.here
        if not h or h[0] != area:
            return None
        k = key_xy(to)
        if k not in h[2]:
            return None
        return math.inf if h[2][k] is None else h[2][k]

    def want_here(self, area, pos, targets):
        """Work out the distances from you (pos) to these targets, if you've moved far enough."""
        if not available():
            return
        targets = tuple(sorted({key_xy(t) for t in targets}))
        with self.lock:
            h = self.here
            if h and h[0] == area and math.dist(h[1], pos) < HERE_MOVED and set(targets) <= set(h[2]):
                return
            w = self.here_want
            if w and w[0] == area and math.dist(w[1], pos) < HERE_MOVED and w[2] == targets:
                return
            self.here_want = (area, (float(pos[0]), float(pos[1])), targets)
        self.wake.set()

    def want_distances(self, jobs):
        """Areas to work out exit-to-exit distances for, most wanted first:
        [(area, layout, sources, targets)]. Replaces the previous list."""
        if not available():
            return
        clean = []
        for area, layout, sources, targets in jobs:
            if layout:
                clean.append((area, layout, tuple(sorted({key_xy(p) for p in sources})),
                              tuple(sorted({key_xy(p) for p in targets}))))
        with self.lock:
            self.jobs = clean
            if not self.fill:         # read what the other window has saved since
                for area, *_ in clean:
                    self.dists_for.pop(area, None)
        self.start()
        self.wake.set()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="paths", daemon=True)
            self.thread.start()

    def _next_job(self):
        """(area, layout, source, targets) still to work out, or None. Loads saved tables on the way."""
        with self.lock:
            jobs = list(self.jobs)
        for area, layout, sources, targets in jobs:
            with self.lock:
                fresh = self.dists_for.get(area) != layout
            if fresh:
                table = load_dists(dist_path(*layout))
                with self.lock:
                    self.dists[area], self.dists_for[area] = table, layout
            with self.lock:
                table = self.dists.get(area, {})
                for src in sources:
                    missing = tuple(t for t in targets if (src, t) not in table and t != src)
                    if missing:
                        return area, layout, src, missing
        return None

    def _ask(self, area, pos, target):
        f = self.failed
        if f and f[0] == area and _same(f[2], target) and math.dist(f[1], pos) < STRAY \
                and time.time() - f[3] < RETRY_AFTER:
            return                                     # just failed from here: don't spin
        w = self.want
        if w and w[0] == area and _same(w[2], target) and math.dist(w[1], pos) < 1.0:
            return
        self.want = (area, pos, target)
        self.wake.set()

    def _run(self):
        grids, grids_host = None, object()
        cache = {}                                     # layout -> grid (the area you're in + one more)
        while True:
            self.wake.wait()
            self.wake.clear()
            with self.lock:
                layout, host, want, here_want = self.layout, self.host, self.want, self.here_want
            try:
                if grids is None or host != grids_host:
                    grids_host = host
                    grids = Grids(self.make_resources(host) if self.make_resources else _resources(host))
                    cache = {}

                def grid_of(area, lay):
                    key = repr(lay)
                    if key not in cache:
                        t0 = time.time()
                        g = grids.grid(*lay)
                        if len(cache) >= 2:
                            cache.pop(next(iter(cache)))
                        cache[key] = g
                        self.log(f"paths: {area} " + (f"walkable grid in {time.time() - t0:.2f}s"
                                                      if g is not None else "has no usable walkmesh"))
                    return cache[key]
                if want and layout and want[0] == layout[0]:
                    self._find(want, grid_of(*layout))
                elif here_want and layout and here_want[0] == layout[0]:
                    self._from_here(here_want, grid_of(*layout))
                else:
                    self._fill_step(grid_of)
            except Exception as e:                     # never break navigation over a path
                self.log(f"paths: {e!r}")
                with self.lock:
                    if want and self.want == want:
                        self.want, self.failed = None, (*want, time.time())
                    if here_want and self.here_want == here_want:
                        self.here_want = None
                time.sleep(1.0)

    def _find(self, want, grid):
        t0 = time.time()
        points = find_path(grid, want[1], want[2]) if grid is not None else None
        with self.lock:
            if self.want != want:
                self.wake.set()                        # asked for something else meanwhile
                return
            self.want = None
            if points:
                self.route, self.failed = Route(want[0], want[2], points), None
            else:
                self.failed = (*want, time.time())
        self.log(f"paths: {want[0]} {'found' if points else 'no path'} "
                 f"in {time.time() - t0:.2f}s" + (f", {len(points) - 2} turns" if points else ""))
        self.wake.set()                                # more may be waiting

    def _from_here(self, here_want, grid):
        area, pos, targets = here_want
        found = distances(grid, pos, targets) if grid is not None else {}
        with self.lock:
            if self.here_want == here_want:
                self.here_want = None
            self.here = (area, pos, {t: found.get(t) for t in targets})
        self.wake.set()

    def _fill_step(self, grid_of):
        """One background search: the distances from one arrival point to an area's exits."""
        job = self._next_job()
        if job is None:
            return
        area, layout, src, targets = job
        grid = grid_of(area, layout) if self.fill else None
        if grid is None:              # no walkmesh (or another window works them out): straight lines
            with self.lock:
                self.jobs = [j for j in self.jobs if j[0] != area]
            self.wake.set()
            return
        found = distances(grid, src, targets)
        with self.lock:
            if self.dists_for.get(area) != layout:
                return
            table = self.dists.setdefault(area, {})
            for t in targets:
                table[(src, t)] = found.get(t)
            done = not any((s_, t) not in table for a_, _lay, srcs, tgts in self.jobs if a_ == area
                           for s_ in srcs for t in tgts if t != s_)
            snapshot = dict(table) if done else None
        if snapshot is not None:
            save_dists(snapshot, dist_path(*layout))
        time.sleep(FILL_PAUSE)
        self.wake.set()


def _resources(host):
    from .resources import Resources
    return Resources(host)
