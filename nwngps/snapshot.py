"""Read the current game state (area, player position, pins, doors) once.

Usage: python -m nwngps.snapshot [--json]
Read-only. Currently finds objects with a full memory scan (~30 s); a direct
pointer path from g_pAppManager will replace that.
"""
import json
import struct
import sys

from . import layout as L
from .memory import GameMemory


def resref(mem, addr):
    b = mem.read(addr, 16) or b""
    return b.split(b"\0", 1)[0].decode("latin-1")


def vec3(mem, addr):
    b = mem.read(addr, 12)
    return [round(v, 3) for v in struct.unpack("<fff", b)] if b else None


def find_objects(mem):
    pats = {struct.pack("<Q", mem.base + rva): cls for cls, rva in L.VTABLES.items()}
    found = {cls: [] for cls in L.VTABLES}
    for p, addr in mem.scan_many(list(pats)):
        found[pats[p]].append(addr)
    return found


def snapshot(mem):
    objs = find_objects(mem)
    areas = []
    for a in objs["CNWCArea"]:
        areas.append({
            "addr": hex(a),
            "id": hex(mem.u32(a + L.AREA_OBJ_ID) or 0),
            "resref": resref(mem, a + L.AREA_RESREF),
            "tileset": resref(mem, a + L.AREA_TILESET),
            "name": mem.exostring(a + L.AREA_NAME),
            "size_tiles": [mem.u32(a + L.AREA_WIDTH), mem.u32(a + L.AREA_HEIGHT)],
        })
    mod = objs["CNWCModule"][0] if objs["CNWCModule"] else None
    return {
        "module": mem.exostring(mod + L.MODULE_NAME) if mod else None,
        "areas": areas,
        "creatures": [{"addr": hex(c), "id": hex(mem.u32(c + L.OBJ_ID) or 0),
                       "area": hex(mem.u64(c + L.OBJ_AREA) or 0),
                       "pos": vec3(mem, c + L.OBJ_POS), "facing": vec3(mem, c + L.OBJ_FACING)}
                      for c in objs["CNWCCreature"]],
        "map_pins": [{"text": mem.exostring(p + L.PIN_TEXT), "pos": vec3(mem, p + L.OBJ_POS)}
                     for p in objs["CNWCMapPin"]],
        "doors": [{"name": mem.exostring(d + L.DOOR_NAME), "tag": mem.exostring(d + L.DOOR_TAG),
                   "pos": vec3(mem, d + L.OBJ_POS)} for d in objs["CNWCDoor"]],
        "counts": {k: len(v) for k, v in objs.items()},
    }


def main():
    mem = GameMemory()
    try:
        s = snapshot(mem)
    finally:
        mem.close()
    if "--json" in sys.argv:
        print(json.dumps(s, indent=1))
        return
    print(f"Module: {s['module']}")
    for a in s["areas"]:
        print(f"Area: {a['name']}  [{a['resref']}]  tileset={a['tileset']}  size={a['size_tiles']}")
    for c in s["creatures"]:
        print(f"Creature {c['id']}: pos={c['pos']} facing={c['facing']}")
    for p in s["map_pins"]:
        print(f"Pin: {p['text']!r:30} at {p['pos']}")
    for d in s["doors"]:
        print(f"Door: {d['name']!r:25} tag={d['tag']!r:20} at {d['pos']}")
    print("counts:", s["counts"])


if __name__ == "__main__":
    main()
