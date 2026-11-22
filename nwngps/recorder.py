"""Background recorder: run while you play; builds the database.

  python -m nwngps.recorder

Every area you enter is stored with its map pins and doors; every area change
is stored as a transition (exit point -> entry point), labelled with the
nearest pin/door. Read-only towards the game. Ctrl+C to stop.
"""
import time

from . import objects
from .db import Store
from .live import Live
from .memory import GameMemory

POLL = 0.25
RESCAN_POIS = 10.0   # seconds between POI refreshes in the same area
SETTLE = 1.5         # seconds after entering before reading objects (area finishing load)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def record_pois(mem, store, st, table):
    area = st["area_ptr"]
    pois = objects.map_pins(mem, area)
    if table:
        pois += objects.doors(mem, area, table)
    new = 0
    for p in pois:
        before = store.stats()["pois"]
        store.upsert_poi(st["area"], p["kind"], p["name"], p["tag"], *[round(v, 2) for v in p["pos"]])
        new += store.stats()["pois"] - before
    store.commit()
    return len(pois), new


def main():
    mem = GameMemory()
    live = Live(mem)
    store = None
    table = None
    last = None              # last good state (with position) in the current area
    entered_at = 0.0
    pois_at = 0.0
    log("recorder started; waiting for game state")
    try:
        while True:
            st = live.read()
            if not st or not st["area"] or not st["pos"]:
                time.sleep(POLL)
                continue
            if store is None:
                mod = mem.exostring(mem.u64(live._internal() + 0x30) + 0x18) or "arelith"
                store = Store(mod)
                log(f"database: {store.path}  {store.stats()}")
            now = time.time()
            if last is None or st["area"] != last["area"]:
                store.upsert_area(st["area"], st.get("area_name"), st.get("tileset"), *st.get("size", (None, None)),
                                  visit=True)
                if last is not None:
                    tid, new = store.add_transition(last["area"], last["pos"], st["area"], st["pos"])
                    log(f"{'NEW ' if new else ''}transition: {store.area_name(last['area'])} {last['pos'][:2]} "
                        f"-> {st.get('area_name')} {st['pos'][:2]}")
                else:
                    log(f"in {st.get('area_name')} [{st['area']}] at {st['pos'][:2]}")
                entered_at, pois_at = now, 0.0
            last = st
            if now - entered_at > SETTLE and now - pois_at > RESCAN_POIS:
                if table and not any(table.lookup(i) for i in objects.area_ids(mem, st["area_ptr"])[:20]):
                    log("object table moved; locating again")
                    table = None
                if table is None:
                    table = objects.ObjectTable.locate(mem, st["area_ptr"], log=log)
                    if table is None:
                        log("object table not found; recording pins only")
                        table = False
                n, new = record_pois(mem, store, st, table or None)
                if new:
                    log(f"  {new} new POIs ({n} visible) in {st.get('area_name')}")
                pois_at = now
            time.sleep(POLL)
    except KeyboardInterrupt:
        log("stopped")
    finally:
        if store:
            log(f"database: {store.stats()}")
            store.close()
        mem.close()


if __name__ == "__main__":
    main()
