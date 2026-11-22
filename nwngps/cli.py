"""Search and routing over the recorded database.

  python -m nwngps.cli stats
  python -m nwngps.cli areas
  python -m nwngps.cli find <text>
  python -m nwngps.cli route <destination text> [--from <area resref>]
  python -m nwngps.cli import-jsonl <transitions.jsonl>

Without --from, `route` starts from where your character is right now (game must be running).
"""
import json
import math
import sys
import time

from . import route as R
from .db import Store


def direction(dx, dy):
    # NWN: +y is north, +x is east
    ang = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((ang + 22.5) // 45) % 8]


def current_position():
    from .session import IN_GAME, Session
    s = Session(log=lambda *a: None)
    try:
        for _ in range(40):                 # up to ~10 s (object table locate on first call)
            snap = s.poll()
            if snap.state == IN_GAME:
                return snap.area, snap.pos
            time.sleep(0.25)
    finally:
        s.close()
    sys.exit(f"can't read your position (game state: {snap.state})")


def resolve_destination(store, text):
    hits = store.search(text)
    if not hits:
        sys.exit(f"nothing matches {text!r}")
    h = hits[0]
    goal_xy = (h["x"], h["y"]) if h["x"] is not None else None
    return h, goal_xy, hits


def cmd_route(store, args):
    frm = None
    if "--from" in args:
        i = args.index("--from")
        frm = args[i + 1]
        args = args[:i] + args[i + 2:]
        start_area, start_pos = frm, None
    else:
        start_area, start_pos = current_position()
    dest, goal_xy, hits = resolve_destination(store, " ".join(args))
    if start_pos is None:
        a = store.area(start_area)
        start_pos = ((a["width"] or 0) * 5, (a["height"] or 0) * 5) if a else (0, 0)
    print(f"From: {store.area_name(start_area)}  ({start_pos[0]:.0f}, {start_pos[1]:.0f})")
    print(f"To:   {dest['name']}  in {store.area_name(dest['area'])}")
    if len(hits) > 1:
        print(f"      (best of {len(hits)} matches; `find` lists them all)")
    steps = R.plan(store.transitions(), start_area, start_pos, dest["area"], goal_xy)
    if steps is None:
        print("No known route yet. Explore more with the recorder running.")
        return
    if not steps:
        print("You're already in that area.")
    pos = start_pos
    for i, t in enumerate(steps, 1):
        via = store.poi(t["via_poi"]) if t["via_poi"] else store.nearest_poi(t["from_area"], t["from_x"], t["from_y"])
        label = f'"{via["name"]}"' if via and via["name"] else f"exit at ({t['from_x']:.0f}, {t['from_y']:.0f})"
        dx, dy = t["from_x"] - pos[0], t["from_y"] - pos[1]
        hop = f"  [server transfer {t['from_server']} -> {t['to_server']}]" if t["kind"] == "portal" else ""
        print(f" {i}. In {store.area_name(t['from_area'])}: go {direction(dx, dy)} ~{math.hypot(dx, dy):.0f} m "
              f"to {label} -> {store.area_name(t['to_area'])}{hop}")
        pos = (t["to_x"], t["to_y"])
    if goal_xy:
        dx, dy = goal_xy[0] - pos[0], goal_xy[1] - pos[1]
        print(f" {len(steps) + 1}. Then go {direction(dx, dy)} ~{math.hypot(dx, dy):.0f} m to {dest['name']}.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    store = Store()
    try:
        if cmd == "stats":
            print(store.stats())
        elif cmd == "areas":
            for a in store.db.execute("SELECT * FROM areas ORDER BY name"):
                print(f"{a['resref']:18} {a['name']}  ({a['width']}x{a['height']}, {a['tileset']}, visits={a['visits']})")
        elif cmd == "find":
            for h in store.search(" ".join(args)):
                where = f" at ({h['x']:.0f}, {h['y']:.0f})" if h["x"] is not None else ""
                print(f"[{h['kind']:4}] {h['name']}  — {store.area_name(h['area'])}{where}")
        elif cmd == "route":
            cmd_route(store, args)
        elif cmd == "import-jsonl":
            n = 0
            for line in open(args[0], encoding="utf-8"):
                ev = json.loads(line)
                store.upsert_area(ev["to"], ev.get("to_name"))
                if ev.get("from") and ev.get("from_pos") and ev.get("to_pos"):
                    store.add_transition(ev["from"], ev["from_pos"], ev["to"], ev["to_pos"])
                    n += 1
            print(f"imported {n} transitions; {store.stats()}")
        else:
            print(__doc__)
    finally:
        store.close()


if __name__ == "__main__":
    main()
