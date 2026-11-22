"""Shortest route between areas over recorded transitions.

Nodes are (area, x, y) points where you are standing; from a point you can walk
to any recorded exit in the same area (cost = straight-line distance) and take
it (cost = LOAD_COST, arriving at the recorded entry point of the next area).
"""
import heapq
import math

LOAD_COST = 15.0      # metres-equivalent penalty per loading screen
REVERSE_COST = 30.0   # extra penalty for an assumed (never walked) reverse edge
REVERSE_NEAR = 8.0    # a recorded edge this close to the arrival point already covers the way back


def with_reverse_edges(transitions):
    """Recorded edges plus an assumed reverse for each one nobody has walked back yet.
    NWN transitions are almost always two-way and you arrive next to the way back."""
    edges = [dict(t) for t in transitions]
    for t in list(edges):
        covered = any(e["from_area"] == t["to_area"] and e["to_area"] == t["from_area"]
                      and math.hypot(e["from_x"] - t["to_x"], e["from_y"] - t["to_y"]) < REVERSE_NEAR
                      for e in edges)
        if not covered:
            r = dict(t)
            r.update(from_area=t["to_area"], from_x=t["to_x"], from_y=t["to_y"],
                     to_area=t["from_area"], to_x=t["from_x"], to_y=t["from_y"],
                     from_server=t.get("to_server"), to_server=t.get("from_server"),
                     via_poi=None, assumed=True)
            edges.append(r)
    return edges


def plan(transitions, start_area, start_xy, goal_area, goal_xy=None, assume_reverse=True):
    """Return list of transition rows (dicts) to follow, or None if unreachable."""
    edges = with_reverse_edges(transitions) if assume_reverse else [dict(t) for t in transitions]
    by_area = {}
    for t in edges:
        by_area.setdefault(t["from_area"], []).append(t)

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
