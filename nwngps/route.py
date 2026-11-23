"""Shortest route between areas over recorded transitions.

Nodes are (area, x, y) points where you are standing; from a point you can walk
to any recorded exit in the same area (cost = straight-line distance) and take
it (cost = LOAD_COST, arriving at the recorded entry point of the next area).
"""
import heapq
import math

from .edges import NEVER_ROUTED, REVERSIBLE

LOAD_COST = 15.0      # metres-equivalent penalty per loading screen
REVERSE_COST = 30.0   # extra penalty for an assumed (never walked) reverse edge
REVERSE_NEAR = 8.0    # a recorded edge this close to the arrival point already covers the way back


def kind_of(t):
    return t.get("kind") or "walk"


def routable(transitions):
    """Plain-dict copies of the edges directions may use (never death links)."""
    return [e for e in (dict(t) for t in transitions) if kind_of(e) not in NEVER_ROUTED]


def with_reverse_edges(transitions):
    """Recorded edges plus an assumed reverse for each one nobody has walked back yet.
    NWN transitions are almost always two-way and you arrive next to the way back. Not so for
    jumps (spells, scripts), deaths or respawns: those get no assumed way back."""
    edges = routable(transitions)
    by_pair = {}                         # (from, to) -> edges: keeps this linear in the edge count
    for e in edges:
        by_pair.setdefault((e["from_area"], e["to_area"]), []).append(e)
    for t in list(edges):
        if kind_of(t) not in REVERSIBLE:
            continue
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


def edge_index(transitions, assume_reverse=True):
    """Prepared graph for plan(): {from_area: [edge, ...]}. Build once, reuse until the data changes."""
    edges = (with_reverse_edges(transitions) if assume_reverse else
             routable(transitions))
    by_area = {}
    for t in edges:
        by_area.setdefault(t["from_area"], []).append(t)
    return by_area


def plan(transitions, start_area, start_xy, goal_area, goal_xy=None, assume_reverse=True, index=None):
    """Return list of transition rows (dicts) to follow, or None if unreachable.
    Pass `index` (from edge_index) to skip rebuilding the graph."""
    by_area = index if index is not None else edge_index(transitions, assume_reverse)

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
        if area == goal_area:
            extra = math.hypot(goal_xy[0] - x, goal_xy[1] - y) if goal_xy else 0.0
            if final is None or cost + extra < final[0]:
                final = (cost + extra, node)
            continue
        if final and cost >= final[0]:
            break
        for t in by_area.get(area, []):
            nxt = (t["to_area"], round(t["to_x"], 1), round(t["to_y"], 1))
            c = (cost + math.hypot(t["from_x"] - x, t["from_y"] - y) + LOAD_COST
                 + (REVERSE_COST if t.get("assumed") else 0.0))
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
