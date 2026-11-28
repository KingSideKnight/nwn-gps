"""Turn-by-turn navigation state, independent of any UI.

Navigator.update(snapshot) -> Guidance: what to show right now (next target,
distance, bearing relative to the character's facing, step text). The route is
re-planned on area changes and every few seconds as you move.
"""
import math
import time
from dataclasses import dataclass, field

from . import route as R

ARRIVE_DIST = 4.0      # metres from the destination counts as arrived
REPLAN_EVERY = 3.0     # seconds
SWITCH_MIN, SWITCH_SHARE = 20.0, 0.10   # a new route must be this much shorter (metres, share) to switch to it
FILL_AREAS = 200       # areas (nearest first) whose walking distances are worked out in the background


def bearing(dx, dy):
    """Compass bearing in degrees, 0 = north (+y), 90 = east (+x)."""
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def compass(deg):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) // 45) % 8]


@dataclass
class Guidance:
    status: str                      # NAV | ARRIVED | NO_ROUTE | WAITING
    dest_name: str = ""
    line1: str = ""                  # main instruction
    line2: str = ""                  # secondary detail
    target: tuple = None             # (x, y) in the current area
    distance: float = None
    bearing: float = None            # compass bearing to target
    relative: float = None           # degrees: 0 ahead, +90 right, -90 left
    step: int = 0
    steps: int = 0
    route_exits: list = field(default_factory=list)   # exits in the current area that are on the route
    path: list = None                # the way on foot to target: [(x, y), ...] from you (None: straight line)


class Navigator:
    def __init__(self, store, dest, paths=None):
        """dest: row from Store.search() (kind, area, name, x, y). paths: a walkmesh.Paths for
        the way on foot inside the area you're in (else straight lines)."""
        self.store, self.dest, self.paths = store, dest, paths
        self.goal_xy = (dest["x"], dest["y"]) if dest["x"] is not None else None
        self.plan, self.plan_area, self.plan_t = None, None, 0.0

    def _graph(self):
        """Route graph, rebuilt only when the recorder has added or updated transitions."""
        version = self.store.links_version()
        if version != getattr(self, "_graph_version", None):
            self._graph_index = R.edge_index(self.store.transitions(), places=self.store.exit_places())
            self._graph_version = version
            arrivals = {}
            for edges in self._graph_index.values():
                for t in edges:
                    arrivals.setdefault(t["to_area"], set()).add((t["to_x"], t["to_y"]))
            self._arrivals = arrivals
        return self._graph_index

    def _walk(self, area, frm, to, first):
        """Metres on foot inside an area, if worked out yet (see route.leg)."""
        return self.paths.here_cost(area, to) if first else self.paths.cost(area, frm, to)

    def _targets(self, area, index):
        out = [(t["from_x"], t["from_y"]) for t in index.get(area, ())]
        if area == self.dest["area"] and self.goal_xy:
            out.append(self.goal_xy)
        return out

    def _feed(self, snap, index, plan):
        """Ask for the walking distances routing needs: from you to this area's exits, then (in the
        background) between the exits of the areas on the route, then of the areas nearest you."""
        self.paths.want_here(snap.area, snap.pos[:2], self._targets(snap.area, index))
        on_route = [t["to_area"] for t in plan or ()]
        key = (snap.area, self._graph_version, tuple(on_route))
        if key == getattr(self, "_fed", None):
            return
        self._fed = key
        order, seen = [], set()
        for area in [snap.area] + on_route:
            if area not in seen:
                seen.add(area)
                order.append(area)
        frontier = [snap.area]
        while frontier and len(seen) < FILL_AREAS:          # then the areas nearest you, a hop at a time
            nxt = []
            for area in frontier:
                for t in index.get(area, ()):
                    if t["to_area"] not in seen and len(seen) < FILL_AREAS:
                        seen.add(t["to_area"])
                        order.append(t["to_area"])
                        nxt.append(t["to_area"])
            frontier = nxt
        jobs = []
        for area in order:
            sources = self._arrivals.get(area, ())
            targets = self._targets(area, index)
            if sources and targets:
                jobs.append((area, self.store.tiles(area), sources, targets))
        self.paths.want_distances(jobs)

    def _carried_on(self, snap, index):
        """The route we were following, from where you are now (or None)."""
        old = self.plan
        if not old:
            return None
        if self.plan_area != snap.area:
            if old[0]["to_area"] != snap.area:
                return None
            old = old[1:]                                    # you took its first exit
        if not all(t in index.get(t["from_area"], ()) for t in old):
            return None                                      # the map changed under it
        return old

    def _replan(self, snap):
        index = self._graph()
        walk = self._walk if self.paths else None
        new = R.plan(None, snap.area, snap.pos[:2], self.dest["area"], self.goal_xy, index=index, walk=walk)
        old = self._carried_on(snap, index) if getattr(self, "_informed", False) else None
        if new is not None and old is not None and new != old:
            # only switch to a clearly shorter route, so near-equal ones don't take turns
            pos = snap.pos[:2]
            c_new = R.route_cost(new, snap.area, pos, self.goal_xy, walk)
            c_old = R.route_cost(old, snap.area, pos, self.goal_xy, walk)
            if c_new is not None and c_old is not None and c_new > c_old - max(SWITCH_MIN, SWITCH_SHARE * c_old):
                new = old
        self.plan = new
        self.plan_area, self.plan_t = snap.area, time.time()
        # A first guess (made before the walking distance from you was known) may still change freely.
        first = new[0] if new else None
        self._informed = (not self.paths or first is None
                          or self.paths.here_cost(snap.area, (first["from_x"], first["from_y"])) is not None)
        if self.paths:
            self._feed(snap, index, new)

    def label(self, t):
        via = self.store.poi(t["via_poi"]) if t.get("via_poi") else \
            self.store.nearest_poi(t["from_area"], t["from_x"], t["from_y"])
        return f'"{via["name"]}"' if via and via["name"] and via["name"] not in ("Door",) else "the exit"

    def update(self, snap):
        g = Guidance("WAITING", dest_name=self.dest["name"])
        if snap.state != "IN_GAME":
            g.line1 = {"NO_GAME": "Game not running", "MENU": "In menus", "LOADING": "Loading..."}.get(snap.state, "")
            return g
        if self.plan is None or snap.area != self.plan_area or time.time() - self.plan_t > REPLAN_EVERY:
            self._replan(snap)
        x, y = snap.pos[:2]
        if self.plan is None:
            g.status, g.line1 = "NO_ROUTE", "No known route yet"
            g.line2 = "Explore with the recorder running"
            return g
        if self.plan:
            t = self.plan[0]
            g.target = (t["from_x"], t["from_y"])
            dest_area = self.store.area_name(t["to_area"])
            hop = " (server transfer)" if t.get("kind") == "portal" else ""
            g.line1 = f"Take {self.label(t)} to {dest_area}{hop}"
            if t.get("ambiguous"):
                g.line2 = f"This exit has led to different places: pick {dest_area} if asked"
            elif t.get("assumed"):
                g.line2 = "Way back assumed (not walked yet)"
            elif t.get("kind") == "jump":
                g.line2 = "Teleport spot: use the portal / object here"
            elif t.get("kind") == "respawn":
                g.line2 = "The way out after dying"
            else:
                g.line2 = ""
            g.step, g.steps = 1, len(self.plan) + (1 if self.goal_xy else 0)
            g.route_exits = [g.target]
        elif self.goal_xy:
            g.target = self.goal_xy
            g.line1 = f"Go to {self.dest['name']}"
            g.step = g.steps = 1
        else:
            g.status, g.line1 = "ARRIVED", f"You're in {self.dest['name']}"
            return g
        dx, dy = g.target[0] - x, g.target[1] - y
        g.distance = math.hypot(dx, dy)
        if not self.plan and g.distance <= ARRIVE_DIST:
            g.status, g.line1, g.line2 = "ARRIVED", f"Arrived: {self.dest['name']}", ""
            return g
        g.status = "NAV"
        walk = self.paths.walk(snap.area, (x, y), g.target) if self.paths else None
        if walk:                         # on foot: head for the next turn; the distance is walking
            g.path, g.distance = walk.points, walk.length
            dx, dy = walk.aim[0] - x, walk.aim[1] - y
        g.bearing = bearing(dx, dy)
        if snap.facing and (snap.facing[0] or snap.facing[1]):
            facing = bearing(snap.facing[0], snap.facing[1])
            g.relative = (g.bearing - facing + 540.0) % 360.0 - 180.0
        return g
