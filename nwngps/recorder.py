"""Background recorder: run while you play; builds the database.

  python -m nwngps.recorder

Survives the game not running yet, menus, loading screens, relogs, game restarts
and moving between servers. One database per world (all servers that share an
NWSync host, e.g. every Arelith server, share one map).

Edges:
  walk    area change on the same server with only loading screens in between
  portal  arrived on a different server of the same world within PORTAL_WINDOW;
          confirmed straight away if no menu was seen in between, otherwise
          recorded unconfirmed (could be a manual relog) until seen again.
Anything else (long gaps, menus on the same server, game restarts) is a relog: no edge.
Read-only towards the game. Ctrl+C to stop.
"""
import time

from . import maps, objects
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

    def store(self, world):
        if world not in self.stores:
            self.stores[world] = Store(world)
            s = self.stores[world]
            log(f"world {world}: {s.path.name} {s.stats()}")
        return self.stores[world]

    def on_arrival(self, snap):
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
        if prev.server != snap.server:
            if gap <= PORTAL_WINDOW:
                confirmed = not self.saw_menu
                _, new = st.add_transition(prev.area, prev.pos, snap.area, snap.pos, prev.server, snap.server,
                                           kind="portal", confirmed=confirmed)
                log(f"{'NEW ' if new else ''}PORTAL{'' if confirmed else ' (unconfirmed: menu seen)'}: "
                    f"{prev.server}/{prev.area_name} {prev.pos[:2]} -> {snap.server}/{snap.area_name} {snap.pos[:2]}")
            else:
                log(f"relog on {snap.server} after {gap:.0f}s; no edge recorded")
            return
        if self.saw_menu or gap > WALK_WINDOW:
            log(f"relog on {snap.server} ({'menu' if self.saw_menu else f'{gap:.0f}s gap'}): "
                f"in {snap.area_name}; no edge recorded")
            return
        if prev.area != snap.area:
            _, new = st.add_transition(prev.area, prev.pos, snap.area, snap.pos, prev.server, snap.server)
            log(f"{'NEW ' if new else ''}transition: {prev.area_name} {prev.pos[:2]} -> {snap.area_name} {snap.pos[:2]}")

    def record_pois(self, snap):
        st = self.store(snap.world)
        mem, table = self.session.mem, self.session.table
        if snap.size and not st.tiles(snap.area):
            tiles = maps.read_tiles(mem, snap.area_ptr, *snap.size)
            if tiles:
                st.save_tiles(snap.area, snap.tileset, *snap.size, tiles)
                log(f"  tile layout saved ({snap.size[0]}x{snap.size[1]}, {snap.tileset})")
        pois = objects.map_pins(mem, snap.area_ptr) + (objects.doors(mem, snap.area_ptr, table) if table else [])
        before = st.stats()["pois"]
        for p in pois:
            st.upsert_poi(snap.area, p["kind"], p["name"], p["tag"], *[round(v, 2) for v in p["pos"]])
        st.commit()
        new = st.stats()["pois"] - before
        if new:
            log(f"  {new} new POIs ({len(pois)} visible) in {snap.area_name}")

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
    Recorder().run()
