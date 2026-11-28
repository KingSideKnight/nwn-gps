"""Shortest route between areas over recorded transitions.

Nodes are (area, x, y) points where you are standing; from a point you can walk
to any recorded exit in the same area (cost = the distance on foot where it's known,
else the straight line) and take it (cost = LOAD_COST, arriving at the recorded entry
point of the next area).
"""
import heapq
import math

from .edges import NEVER_ROUTED, REVERSIBLE, natural_arrival

LOAD_COST = 15.0      # metres-equivalent penalty per loading screen
REVERSE_COST = 30.0   # extra penalty for an assumed (never walked) reverse edge
REVERSE_NEAR = 8.0    # a recorded edge this close to the arrival point already covers the way back
AMBIGUOUS_COST = 400.0   # metres-equivalent: an exit that has led to different areas is a last resort
SAME_SPOT = 2.0       # metres: exits without a known object this close count as the same exit
NO_WAY_COST = 300.0   # metres-equivalent: no way on foot inside the area (the tiles may be wrong: last resort)


def kind_of(t):
    return t.get("kind") or "walk"


def routable(transitions):
    """Plain-dict copies of the edges directions may use (never death links). Exits that have taken
    you to different areas are marked "ambiguous": where they lead depends on something we can't
    see (a portal that returns you where you came from, a conversation choice), so routes use
    them only when there's no other way."""
    edges = [e for e in (dict(t) for t in transitions) if kind_of(e) not in NEVER_ROUTED]
    mark_ambiguous(edges)
    return edges


def mark_ambiguous(edges):
    """Set e["ambiguous"] on every edge whose exit (same object, else the same spot) has recorded
    more than one destination area."""
    by_exit = {}
    loose = {}
    for e in edges:
        if e.get("via_poi") is not None:
            by_exit.setdefault((e["from_area"], e["via_poi"]), []).append(e)
        else:
            loose.setdefault(e["from_area"], []).append(e)
    groups = list(by_exit.values())
    for area_edges in loose.values():        # no object: group exits standing on the same spot
        left = list(area_edges)
        while left:
            first = left.pop()
            group = [first] + [e for e in left if math.hypot(e["from_x"] - first["from_x"],
                                                              e["from_y"] - first["from_y"]) <= SAME_SPOT]
            left = [e for e in left if e not in group]
            groups.append(group)
    for group in groups:
        if len({e["to_area"] for e in group}) > 1:
            for e in group:
                e["ambiguous"] = True
    return edges


def arrived_at_exit(t, places):
    """Did edge t drop you next to a door, pin or map edge of the area it leads to? True if
    `places` is None or doesn't know (then the old assumption stands)."""
    if places is None:
        return True
    spots = places["pois"].get(t["to_area"], ())
    near = min((math.hypot(x - t["to_x"], y - t["to_y"]) for x, y in spots), default=None)
    ok = natural_arrival(t["to_x"], t["to_y"], places["sizes"].get(t["to_area"]), near)
    return ok is not False


def with_reverse_edges(transitions, places=None):
    """Recorded edges plus an assumed reverse for each one nobody has walked back yet.
    NWN transitions are almost always two-way and you arrive next to the way back. Not so for
    jumps (spells, scripts), deaths or respawns, for exits that have led to different places, or
    when you came out in the middle of an area (a portal back from a plane, a scripted drop):
    those get no assumed way back. `places` (Store.exit_places()) enables that last check."""
    edges = routable(transitions)
    by_pair = {}                         # (from, to) -> edges: keeps this linear in the edge count
    for e in edges:
        by_pair.setdefault((e["from_area"], e["to_area"]), []).append(e)
    for t in list(edges):
        if kind_of(t) not in REVERSIBLE or t.get("ambiguous") or not arrived_at_exit(t, places):
            continue                     # (an exit that goes different places says nothing about a way back)
        covered = any(math.hypot(e["from_x"] - t["to_x"], e["from_y"] - t["to_y"]) < REVERSE_NEAR
                      for e in by_pair.get((t["to_area"], t["from_area"]), ()))
        if not covered:
            r = dict(t)
            r.update(from_area=t["to_area"], from_x=t["to_x"], from_y=t["to_y"],
                     to_area=t["from_area"], to_x=t["from_x"], to_y=t["from_y"],
                     from_server=t.get("to_server"), to_server=t.get("from_server"),
                     via_poi=None, assumed=True)
            edges.append(r)
    return edges


def edge_index(transitions, assume_reverse=True, places=None):
    """Prepared graph for plan(): {from_area: [edge, ...]}. Build once, reuse until the data changes."""
    edges = (with_reverse_edges(transitions, places) if assume_reverse else
             routable(transitions))
    by_area = {}
    for t in edges:
        by_area.setdefault(t["from_area"], []).append(t)
    return by_area


def leg(walk, area, frm, to, first):
    """Metres from frm to to inside `area`: on foot if `walk` knows (walk(area, frm, to, first)
    -> metres, math.inf for no way, or None), else the straight line."""
    straight = math.hypot(to[0] - frm[0], to[1] - frm[1])
    d = walk(area, frm, to, first) if walk else None
    if d is None:
        return straight
    if d == math.inf:
        return straight + NO_WAY_COST
    return max(d, straight)


def step_cost(t):
    """The cost of taking exit t itself (a loading screen, plus doubts about it)."""
    return LOAD_COST + (REVERSE_COST if t.get("assumed") else 0.0) + (AMBIGUOUS_COST if t.get("ambiguous") else 0.0)


def route_cost(steps, start_area, start_xy, goal_xy=None, walk=None):
    """What plan() would count for following `steps` from start: legs on foot, exits, and the
    last leg to goal_xy."""
    area, here, first, total = start_area, (start_xy[0], start_xy[1]), True, 0.0
    for t in steps:
        if t["from_area"] != area:
            return None                       # not a route from here
        total += leg(walk, area, here, (t["from_x"], t["from_y"]), first) + step_cost(t)
        area, here, first = t["to_area"], (round(t["to_x"], 1), round(t["to_y"], 1)), False
    if goal_xy:
        total += leg(walk, area, here, goal_xy, first)
    return total


def plan(transitions, start_area, start_xy, goal_area, goal_xy=None, assume_reverse=True, index=None, places=None,
         walk=None):
    """Return list of transition rows (dicts) to follow, or None if unreachable.
    Pass `index` (from edge_index) to skip rebuilding the graph, and `walk` (see leg()) for
    distances on foot."""
    by_area = index if index is not None else edge_index(transitions, assume_reverse, places)

    start = (start_area, round(start_xy[0], 1), round(start_xy[1], 1))
    best = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    final = None
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best.get(node, math.inf):
            continue
        area, x, y = node
        first = node == start
        if area == goal_area:
            extra = leg(walk, area, (x, y), goal_xy, first) if goal_xy else 0.0
            if final is None or cost + extra < final[0]:
                final = (cost + extra, node)
            continue
        if final and cost >= final[0]:
            break
        for t in by_area.get(area, []):
            nxt = (t["to_area"], round(t["to_x"], 1), round(t["to_y"], 1))
            c = cost + leg(walk, area, (x, y), (t["from_x"], t["from_y"]), first) + step_cost(t)
            if c < best.get(nxt, math.inf):
                best[nxt] = c
                prev[nxt] = (node, t)
                heapq.heappush(heap, (c, nxt))
    if not final:
        return None
    steps, node = [], final[1]
    while node in prev:
        node, t = prev[node]
        steps.append(t)
    return list(reversed(steps))
