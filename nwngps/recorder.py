"""Background recorder: run while you play; builds the database.

  python -m nwngps.recorder

Survives the game not running yet, menus, loading screens, relogs, game restarts
and moving between servers. One database per world (all servers that share an
NWSync host, e.g. every Arelith server, share one map).

Edges (an area change with only loading screens in between; see edges.py for the kinds):
  walk / portal   left by a door, map pin or the map edge (portal = onto another server
                  within PORTAL_WINDOW; unconfirmed if a menu was seen in between)
  jump            left from anywhere else (spell, recall stone, script, DM, graveyard respawn)
  death / respawn into / out of a death area (settings "death_areas")
Anything else (long gaps, menus on the same server, game restarts) is a relog: no edge.
Settings "dm_mode": record areas, pins, doors and maps but no edges (experimental).
Read-only towards the game. Ctrl+C to stop.
"""
import time

from . import config, edges, maps, objects
from .db import Store
from .session import IN_GAME, MENU, NO_GAME, Session

POLL = 0.25
RESCAN_POIS = 10.0
SETTLE = 1.5
PORTAL_WINDOW = 180.0     # seconds: max gap between leaving one server and arriving on another
WALK_WINDOW = 60.0        # seconds: max loading gap for a normal area change
MENU_MIN = 3.0            # seconds in MENU before it counts (brief flickers happen during loads)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Recorder:
    def __init__(self):
        self.session = Session(log=log)
        self.stores = {}
        self.last = None            # last IN_GAME snapshot
        self.saw_menu = False       # menu visited since `last`
        self.restarted = False      # game exited since `last`
        self.menu_since = None
        self.entered_at = 0.0
        self.pois_at = 0.0
        self.settings = config.load_settings()
        self.dm_logged = False
        self.visit = None           # this area visit: POI ids seen, scans, layout check (end_visit)

    def store(self, world):
        if world not in self.stores:
            self.stores[world] = Store(world)
            s = self.stores[world]
            log(f"world {world}: {s.path.name} {s.stats()}")
        return self.stores[world]

    def edge(self, st, prev, snap, menu_seen=False):
        """Classify and record one area change."""
        via = st.nearest_poi(prev.area, prev.pos[0], prev.pos[1], max_dist=edges.DOOR_NEAR)
        d = edges.dist(via["x"], via["y"], prev.pos[0], prev.pos[1]) if via else None
        kind, confirmed = edges.classify(prev.area, prev.area_name, prev.pos, prev.size, prev.server,
                                         snap.area, snap.area_name, snap.server, d,
                                         self.settings.get("death_areas"))
        if menu_seen and kind == "portal":
            confirmed = False
        _, new = st.add_transition(prev.area, prev.pos, snap.area, snap.pos, prev.server, snap.server,
                                   kind=kind, confirmed=confirmed)
        label = {"walk": "transition", "portal": "PORTAL", "jump": "JUMP (not used for directions yet)",
                 "death": "DEATH (never used for directions)", "respawn": "respawn"}[kind]
        if kind == "portal" and not confirmed:
            label += " (unconfirmed: menu seen)"
        log(f"{'NEW ' if new else ''}{label}: {prev.server}/{prev.area_name} {prev.pos[:2]} -> "
            f"{snap.server}/{snap.area_name} {snap.pos[:2]}")

    def on_arrival(self, snap):
        self.settings = config.load_settings()     # cheap; lets dm_mode / death_areas change live
        st = self.store(snap.world)
        st.upsert_area(snap.area, snap.area_name, snap.tileset, *(snap.size or (None, None)),
                       visit=True, server=snap.server)
        prev = self.last
        if prev is None:
            log(f"in {snap.area_name} [{snap.area}] on {snap.server} at {snap.pos[:2]}")
            return
        gap = snap.t - prev.t
        same_world = prev.world == snap.world
        if not same_world or self.restarted:
            why = "game restarted" if self.restarted else f"different world ({prev.world})"
            log(f"relog ({why}): in {snap.area_name} on {snap.server}; no edge recorded")
            return
        if self.settings.get("dm_mode"):
            if not self.dm_logged:
                log("DM mode is on (settings.json): recording areas, pins, doors and maps, but no links")
                self.dm_logged = True
            return
        self.dm_logged = False
        if prev.server != snap.server:
            if gap <= PORTAL_WINDOW:
                self.edge(st, prev, snap, menu_seen=self.saw_menu)
            else:
                log(f"relog on {snap.server} after {gap:.0f}s; no edge recorded")
            return
        if self.saw_menu or gap > WALK_WINDOW:
            log(f"relog on {snap.server} ({'menu' if self.saw_menu else f'{gap:.0f}s gap'}): "
                f"in {snap.area_name}; no edge recorded")
            return
        if prev.area != snap.area:
            self.edge(st, prev, snap)

    def check_layout(self, st, snap, mem):
        """Read the tile layout; a layout different from the saved one is only accepted once two
        reads in a row agree (a half-loaded area must not overwrite a good map)."""
        tiles = maps.read_tiles(mem, snap.area_ptr, *snap.size)
        if not tiles:
            return
        key = (snap.tileset, *snap.size, tuple(map(tuple, tiles)))
        rec = st.tiles(snap.area)
        if rec and (rec[0], rec[1], rec[2], tuple(map(tuple, rec[3]))) == key:
            self.visit["layout_done"] = True
            return
        if rec and self.visit.get("layout_candidate") != key:
            self.visit["layout_candidate"] = key        # confirm on the next scan
            return
        result = st.check_layout(snap.area, snap.tileset, *snap.size, tiles)
        self.visit["layout_done"] = True
        if result == "new":
            log(f"  tile layout saved ({snap.size[0]}x{snap.size[1]}, {snap.tileset})")
        elif result == "changed":
            log(f"  MAP CHANGED: {snap.area_name}'s layout is different now; saved the new one "
                f"(old one kept: nwngps changes)")
            for tid in st.check_links(snap.area, snap.size):
                log(f"  link {tid} out of {snap.area_name} starts where nothing is any more: "
                    f"not used for directions")
            st.commit()

    def end_visit(self):
        """Leaving an area: pins / doors that weren't there count as missed (see Store.end_visit)."""
        v, self.visit = self.visit, None
        if not v or v["scans"] < 2 or self.settings.get("dm_mode"):
            return
        st = self.store(v["world"])
        res = st.end_visit(v["area"], v["seen"], v["path"], kinds=tuple(sorted(v["kinds"])), size=v["size"])
        if res is None:
            log(f"  {v['name']}: saw too little of what's known to check for removed pins / doors")
            return
        for pid in res["retired"]:
            p = st.poi(pid)
            log(f"  {v['name']}: {p['kind']} \"{p['name'] or ''}\" gone {p['missed']} visits in a row: "
                f"hidden (nwngps changes / restore)")
        for tid in res["stale"]:
            log(f"  link {tid} out of {v['name']} starts where nothing is any more: not used for directions")

    def record_pois(self, snap):
        st = self.store(snap.world)
        mem, table = self.session.mem, self.session.table
        if self.visit is None or self.visit["area"] != snap.area or self.visit["world"] != snap.world:
            self.visit = {"world": snap.world, "area": snap.area, "name": snap.area_name, "size": snap.size,
                          "seen": set(), "kinds": {"pin", "door"}, "scans": 0, "path": []}
        if snap.size and not self.visit.get("layout_done"):
            self.check_layout(st, snap, mem)
        pois = objects.map_pins(mem, snap.area_ptr) + (objects.doors(mem, snap.area_ptr, table) if table else [])
        if not table:
            self.visit["kinds"].discard("door")     # doors weren't read: don't count them as missing
        before = st.stats()["pois"]
        for p in pois:
            self.visit["seen"].add(
                st.upsert_poi(snap.area, p["kind"], p["name"], p["tag"], *[round(v, 2) for v in p["pos"]]))
        self.visit["scans"] += 1
        if snap.pos:           # where you were when the scan ran (doors load only near you)
            self.visit["path"].append(tuple(snap.pos[:2]))
        st.commit()
        new = st.stats()["pois"] - before
        if new:
            log(f"  {new} new POIs ({len(pois)} visible) in {snap.area_name}")
            for tid in st.promote_jumps(snap.area):
                log(f"  link {tid} starts at a door / pin after all: now a normal transition")

    def step(self):
        snap = self.session.poll()
        now = snap.t
        if snap.state == NO_GAME and self.last:
            self.restarted = True
        if snap.state in (MENU, NO_GAME) and self.last:
            self.menu_since = self.menu_since or now
            if now - self.menu_since >= MENU_MIN:
                self.saw_menu = True
        else:
            self.menu_since = None
        if snap.state != IN_GAME:
            return
        changed = (self.last is None or snap.area != self.last.area or snap.server != self.last.server
                   or self.saw_menu or self.restarted)
        if changed:
            self.end_visit()
            self.on_arrival(snap)
            self.entered_at, self.pois_at = now, 0.0
            self.saw_menu = self.restarted = False
        self.last = snap
        if now - self.entered_at > SETTLE and now - self.pois_at > RESCAN_POIS:
            self.record_pois(snap)
            self.pois_at = now

    def run(self):
        log("recorder started (Ctrl+C to stop)")
        try:
            while True:
                try:
                    self.step()
                except Exception as e:      # never die mid-session; log and keep going
                    log(f"error: {e!r}")
                    time.sleep(2)
                time.sleep(POLL)
        except KeyboardInterrupt:
            log("stopped")
        finally:
            for s in self.stores.values():
                log(f"{s.world}: {s.stats()}")
                s.close()
            self.session.close()


if __name__ == "__main__":
    from .single import single_instance
    single_instance("recorder")
    Recorder().run()
