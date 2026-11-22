"""Fast live reader using pointer chains (no memory scan).

  python -m nwngps.live            print area + position a few times a second
  python -m nwngps.live --log F    also append area-change events to F (jsonl)

An area change event records the last position in the old area and the first
position in the new one: that pair is a transition edge for the route graph.
"""
import json
import struct
import sys
import time

from . import layout as L
from .memory import GameMemory


class Live:
    def __init__(self, mem):
        self.mem = mem
        self.vt_area = mem.base + L.VTABLES["CNWCArea"]
        self.vt_creature = mem.base + L.VTABLES["CNWCCreature"]
        self.vt_module = mem.base + L.VTABLES["CNWCModule"]

    def _internal(self):
        p = self.mem.u64(self.mem.base + L.G_APP_MANAGER)
        for off in L.CHAIN_CLIENT_INTERNAL:
            if not p:
                return None
            p = self.mem.u64(p + off)
        return p

    def read(self):
        m = self.mem
        inn = self._internal()
        if not inn:
            return None
        mod = m.u64(inn + L.INTERNAL_MODULE)
        area = m.u64(mod + L.MODULE_CURRENT_AREA) if mod and m.u64(mod) == self.vt_module else None
        holder = m.u64(inn + L.INTERNAL_PLAYER_HOLDER)
        cre = m.u64(holder + L.HOLDER_CREATURE) if holder else None
        st = {"t": round(time.time(), 2), "area": None, "pos": None, "facing": None}
        if area and m.u64(area) == self.vt_area:
            b = m.read(area + L.AREA_RESREF, 16) or b""
            st["area"] = b.split(b"\0", 1)[0].decode("latin-1")
            st["area_name"] = m.exostring(area + L.AREA_NAME)
        if cre and m.u64(cre) == self.vt_creature:
            st["pos"] = [round(v, 2) for v in struct.unpack("<fff", m.read(cre + L.OBJ_POS, 12))]
            st["facing"] = [round(v, 3) for v in struct.unpack("<fff", m.read(cre + L.OBJ_FACING, 12))]
            st["creature_area_ok"] = m.u64(cre + L.OBJ_AREA) == area
        return st


def main():
    log = sys.argv[sys.argv.index("--log") + 1] if "--log" in sys.argv else None
    dur = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else None
    mem = GameMemory()
    live = Live(mem)
    last, prev_area, start = None, None, time.time()
    try:
        while dur is None or time.time() - start < dur:
            st = live.read()
            if st is None:
                print("no client state (loading?)", flush=True)
            else:
                if st["area"] and st["area"] != prev_area:
                    ev = {"event": "area_change", "t": st["t"], "from": prev_area,
                          "from_pos": last["pos"] if last else None,
                          "to": st["area"], "to_name": st.get("area_name"), "to_pos": st["pos"]}
                    print("EVENT", json.dumps(ev), flush=True)
                    if log:
                        with open(log, "a", encoding="utf-8") as f:
                            f.write(json.dumps(ev) + "\n")
                    prev_area = st["area"]
                if st["area"]:
                    last = st
                if not last or st.get("pos") != getattr(main, "_lp", None):
                    print(f"{st['area']} {st['pos']} facing={st['facing']} ok={st.get('creature_area_ok')}", flush=True)
                    main._lp = st.get("pos")
            time.sleep(0.25)
    finally:
        mem.close()


if __name__ == "__main__":
    main()
