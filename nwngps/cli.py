"""Search and routing over the recorded database.

  python -m nwngps.cli stats
  python -m nwngps.cli areas
  python -m nwngps.cli find <text>
  python -m nwngps.cli route <destination text> [--from <area resref>]
  python -m nwngps.cli go <destination text> | --stop     set the in-game HUD's destination
  python -m nwngps.cli worldmap [out.png]                 export the stitched world map
  python -m nwngps.cli export [file.sqlite]               copy of your map database to share
  python -m nwngps.cli export [file.sqlite] --with-places  ... keeping your saved places in it
  python -m nwngps.cli merge <their.sqlite> [--dry-run]   merge a friend's database (backs yours up first)
  python -m nwngps.cli imports                            friends' maps merged so far (id, file, what it added)
  python -m nwngps.cli undo-import <id>                   take one of those out again (backs your map up first)
  python -m nwngps.cli links [area text]                  recorded links between areas (id, kind, trusted?)
  python -m nwngps.cli trust-link <id> | distrust-link <id>   use / stop using a link for directions
  python -m nwngps.cli forget-link <id>                   delete a wrong link (backs your map up first)
  python -m nwngps.cli changes [area text]                what the GPS noticed the server changed
  python -m nwngps.cli restore <id>                       undo one of those (backs your map up first)
  python -m nwngps.cli import-jsonl <transitions.jsonl>

Without --from, `route` starts from where your character is right now (game must be running).
Every command takes --world <name> (see `worlds`); the default is the most recently used world.
"""
import json
import math
import sys
import time
from pathlib import Path

from . import route as R
from .db import Store, file_world, open_untrusted


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
    steps = R.plan(store.transitions(), start_area, start_pos, dest["area"], goal_xy,
                   places=store.exit_places())
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
        if t.get("assumed"):
            hop += "  (assumed way back, not walked yet)"
        print(f" {i}. In {store.area_name(t['from_area'])}: go {direction(dx, dy)} ~{math.hypot(dx, dy):.0f} m "
              f"to {label} -> {store.area_name(t['to_area'])}{hop}")
        pos = (t["to_x"], t["to_y"])
    if goal_xy:
        dx, dy = goal_xy[0] - pos[0], goal_xy[1] - pos[1]
        print(f" {len(steps) + 1}. Then go {direction(dx, dy)} ~{math.hypot(dx, dy):.0f} m to {dest['name']}.")


KIND_NOTE = {"walk": "", "portal": "server portal", "jump": "teleport/script",
             "death": "death - never used", "respawn": "respawn"}


def cmd_links(store, args):
    area = None
    if args:
        text = " ".join(args).lower()
        found = [a["resref"] for a in store.db.execute("SELECT resref, name FROM areas")
                 if text in (a["name"] or "").lower() or text in a["resref"].lower()]
        if not found:
            sys.exit(f"no area matches {text!r}")
        area = found[0]
    rows = store.links(area)
    for r in rows:
        trusted = "yes" if r["confirmed"] and r["kind"] != "death" and r["stale"] is None else "no "
        note = KIND_NOTE.get(r["kind"] or "walk", r["kind"])
        if r["stale"] is not None:
            note = (note + ", " if note else "") + "stale: the map changed (see `changes`)"
        print(f"{r['id']:5}  used for directions: {trusted}  x{r['count'] or 1:<3} "
              f"{r['from_name'] or r['from_area']} ({r['from_x']:.0f}, {r['from_y']:.0f}) -> "
              f"{r['to_name'] or r['to_area']}{'  [' + note + ']' if note else ''}")
    print(f"{len(rows)} links. Fix a wrong one with trust-link / distrust-link / forget-link <id>.")


def cmd_fix_link(store, cmd, args):
    if not args or not args[0].isdigit():
        sys.exit(f"usage: cli {cmd} <id>   (ids are listed by `links`)")
    tid = int(args[0])
    if cmd == "forget-link":
        bak = store.forget_link(tid)
        print(f"link {tid} deleted (backup: {bak})" if bak else f"no link {tid}")
        return
    row = store.db.execute("SELECT kind FROM transitions WHERE id=?", (tid,)).fetchone()
    if row and row["kind"] == "death" and cmd == "trust-link":
        sys.exit("death links are never used for directions; use forget-link if it's wrong")
    ok = store.set_link(tid, confirmed=(cmd == "trust-link"))
    print(f"link {tid} {'will' if cmd == 'trust-link' else 'will not'} be used for directions" if ok
          else f"no link {tid}")


CHANGE_LABEL = {"layout": "MAP LAYOUT CHANGED", "poi_retired": "pin/door hidden (gone)",
                "place_removed": "saved place removed",
                "poi_back": "pin/door back", "link_stale": "link not trusted", "link_back": "link trusted again"}


def cmd_changes(store, args):
    area = None
    if args:
        text = " ".join(args).lower()
        found = [a["resref"] for a in store.db.execute("SELECT resref, name FROM areas")
                 if text in (a["name"] or "").lower() or text in a["resref"].lower()]
        if not found:
            sys.exit(f"no area matches {text!r}")
        area = found[0]
    rows = store.changes(area)
    for c in reversed(rows):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["t"])) if c["t"] else "?"
        undo = "  [undone]" if c["undone"] else ""
        print(f"{c['id']:5}  {when}  {c['area_name'] or c['area']}: "
              f"{CHANGE_LABEL.get(c['what'], c['what'])} - {c['note']}{undo}")
    if not rows:
        print("No map changes noticed yet.")
    else:
        print(f"{len(rows)} changes (newest last). Undo one with: restore <id>")


def cmd_restore(store, args):
    if not args or not args[0].isdigit():
        sys.exit("usage: cli restore <id>   (ids are listed by `changes`)")
    note = store.restore(int(args[0]))
    print(f"undone: {note} (your map was backed up first)" if note
          else f"change {args[0]} can't be undone (unknown, already undone, or nothing to undo)")


def import_line(r):
    """One imported file, for lists: 'id  date  file  +3 areas, +40 places, +12 routes'."""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["t"])) if r["t"] else "?"
    try:
        a = json.loads(r["added"] or "{}")
    except ValueError:
        a = {}
    what = f"+{a.get('areas', 0)} areas, +{a.get('pois', 0)} places, +{a.get('transitions', 0)} routes"
    return f"{when}  {r['file']}  {what}" + ("  [undone]" if r["undone"] else "")


def cmd_imports(store):
    rows = store.imports()
    for r in rows:
        print(f"{r['id']:5}  {import_line(r)}")
    print(f"{len(rows)} imports (newest first). Take one out with: undo-import <id>" if rows
          else "No friends' maps imported yet.")


def cmd_undo_import(store, args):
    if not args or not args[0].isdigit():
        sys.exit("usage: cli undo-import <id>   (ids are listed by `imports`)")
    out = store.undo_import(int(args[0]))
    if not out:
        sys.exit(f"import {args[0]} can't be undone (unknown or already undone)")
    print(f"took {out['file']} out of your map: -{out['areas']} areas, -{out['pois']} places, "
          f"-{out['transitions']} routes, -{out['tile_layouts']} maps; {out['links_untrusted']} links "
          f"untrusted again. Backup: {out['backup']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    world = None
    if "--world" in args:                       # e.g. --world nwnarelith_com (default: most recent)
        i = args.index("--world")
        world, args = args[i + 1], args[:i] + args[i + 2:]
    if cmd == "worlds":
        print("\n".join(Store.worlds()) or "no map databases yet")
        return
    store = Store(world)
    try:
        if cmd == "stats":
            print(store.stats())
        elif cmd == "areas":
            for a in store.db.execute("SELECT * FROM areas ORDER BY name"):
                print(f"{a['resref']:18} {a['name']}  ({a['width']}x{a['height']}, {a['tileset']}, visits={a['visits']})")
        elif cmd == "find":
            for h in store.search(" ".join(args)):
                where = f" at ({h['x']:.0f}, {h['y']:.0f})" if h["x"] is not None else ""
                print(f"[{h['kind']:4}] {h['name']}  - {store.area_name(h['area'])}{where}")
        elif cmd == "route":
            cmd_route(store, args)
        elif cmd == "links":
            cmd_links(store, args)
        elif cmd in ("trust-link", "distrust-link", "forget-link"):
            cmd_fix_link(store, cmd, args)
        elif cmd == "changes":
            cmd_changes(store, args)
        elif cmd == "restore":
            cmd_restore(store, args)
        elif cmd == "imports":
            cmd_imports(store)
        elif cmd == "undo-import":
            cmd_undo_import(store, args)
        elif cmd == "worldmap":
            from . import maps as maps_mod, worldmap
            from .resources import Resources
            out = args[0] if args else "worldmap.png"
            m = maps_mod.Maps(Resources())
            w = worldmap.build(store, m)
            clusters = sorted(set(w.cluster.values()))
            for cid in clusters:
                img, _ = worldmap.render(w, store, m, cid)
                path = out if cid == 0 else out.replace(".png", f"_{cid}.png")
                img.save(path)
                members = [store.area_name(a) for a, c in w.cluster.items() if c == cid]
                print(f"cluster {cid}: {len(members)} areas -> {path} ({img.width}x{img.height})")
            for a, b, off in w.conflicts:
                print(f"  disagreement: links between {store.area_name(a)} and {store.area_name(b)} "
                      f"place them {off} m apart from the rest of the map (see `links`)")
            print(f"interiors attached: {len(w.interiors)}; unplaced areas: "
                  f"{len(set(r['resref'] for r in store.db.execute('SELECT resref FROM areas')) - set(w.origin) - {i[3] for i in w.interiors})}")
        elif cmd == "export":
            keep = "--with-places" in args
            args = [a for a in args if a != "--with-places"]
            dest = args[0] if args else f"{store.path.stem}-share-{time.strftime('%Y%m%d')}.sqlite"
            out = store.export(dest, share=True, keep_places=keep)
            print(f"exported {store.stats()} to {out} (play times removed; saved places "
                  f"{'kept' if keep else 'left out'})")
        elif cmd == "merge":
            if not args:
                sys.exit("usage: cli merge <their.sqlite> [--dry-run]")
            other = args[0]
            if Path(other).resolve() == store.path.resolve():
                sys.exit("that's your own database")
            try:
                con = open_untrusted(other)
                theirs = file_world(con, other)
                con.close()
            except ValueError as e:
                sys.exit(str(e))
            mine = store.my_world()
            if theirs and mine and theirs != mine.lower():
                sys.exit(f"{Path(other).name} is a map of another server ({theirs}); yours is {mine}. "
                         f"Use --world {theirs} to merge into that server's map instead.")
            if "--dry-run" in args:
                import tempfile
                tmp = Path(tempfile.mkdtemp()) / "preview.sqlite"
                store.export(tmp)
                preview = Store(path=tmp)
                try:
                    print("dry run, nothing changed. Would add:", preview.merge(other))
                except ValueError as e:
                    sys.exit(str(e))
                finally:
                    preview.close()
                    tmp.unlink(missing_ok=True)
            else:
                b = store.backup("before-merge")
                print(f"backup: {b}")
                before = store.stats()
                try:
                    added = store.merge(other)
                except ValueError as e:
                    sys.exit(str(e))
                print("added:", added)
                print(f"{before} -> {store.stats()}")
                print(f"to undo: undo-import {added['import_id']}")
        elif cmd == "go":
            from .hud import set_target
            if not args or args == ["--stop"]:
                set_target(None)
                print("destination cleared")
            else:
                hits = store.search(" ".join(args))
                if not hits:
                    sys.exit(f"nothing matches {' '.join(args)!r}")
                set_target(" ".join(args))
                print(f"destination: {hits[0]['name']} in {store.area_name(hits[0]['area'])}")
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
