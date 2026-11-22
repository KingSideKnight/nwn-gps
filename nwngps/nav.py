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


class Navigator:
    def __init__(self, store, dest):
        """dest: row from Store.search() (kind, area, name, x, y)."""
        self.store, self.dest = store, dest
        self.goal_xy = (dest["x"], dest["y"]) if dest["x"] is not None else None
        self.plan, self.plan_area, self.plan_t = None, None, 0.0

    def _graph(self):
        """Route graph, rebuilt only when the recorder has added or updated transitions."""
        version = tuple(self.store.db.execute("SELECT COUNT(*), MAX(last_seen) FROM transitions").fetchone())
        if version != getattr(self, "_graph_version", None):
            self._graph_index = R.edge_index(self.store.transitions())
            self._graph_version = version
        return self._graph_index

    def _replan(self, snap):
        self.plan = R.plan(None, snap.area, snap.pos[:2], self.dest["area"], self.goal_xy, index=self._graph())
        self.plan_area, self.plan_t = snap.area, time.time()

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
            g.line2 = "Way back assumed (not walked yet)" if t.get("assumed") else ""
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
        g.bearing = bearing(dx, dy)
        if snap.facing and (snap.facing[0] or snap.facing[1]):
            facing = bearing(snap.facing[0], snap.facing[1])
            g.relative = (g.bearing - facing + 540.0) % 360.0 - 180.0
        return g
