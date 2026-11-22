"""Enumerate the objects of the current area (map pins, doors) without full scans."""
import struct

from . import layout as L


class ObjectTable:
    """The client's id -> object hash table."""

    def __init__(self, mem, base):
        self.mem, self.base = mem, base

    def lookup(self, oid):
        key = oid & 0x7FFFFFFF
        n = self.mem.u64(self.base + (key % L.OBJTABLE_BUCKETS) * 8)
        hops = 0
        while n and hops < 64:
            if self.mem.u32(n + L.NODE_KEY) == key:
                return self.mem.u64(n + L.NODE_OBJ)
            n = self.mem.u64(n + L.NODE_NEXT)
            hops += 1
        return None

    @classmethod
    def locate(cls, mem, area, log=print, max_candidates=4):
        """Find the table from any live object of `area` (door, placeable or creature):
        scan for their vtables, then for a pointer to one of them; that pointer lives in
        a hash node whose bucket reveals the table base. A few seconds; done once per
        session or after a reconnect."""
        kinds = ("CNWCDoor", "CNWCPlaceable", "CNWCCreature")
        pats = [struct.pack("<Q", mem.base + L.VTABLES[k]) for k in kinds]
        ids = set(area_ids(mem, area))
        if not ids:
            return None
        log("locating object table (one-time scan)...")
        candidates = []
        for _, obj in mem.scan_many(pats):
            if mem.u64(obj + L.OBJ_AREA) == area and mem.u32(obj + L.OBJ_ID) in ids:
                candidates.append(obj)
                if len(candidates) >= max_candidates:
                    break
        for obj in candidates:
            oid = mem.u32(obj + L.OBJ_ID)
            key = oid & 0x7FFFFFFF
            for ref in mem.scan(struct.pack("<Q", obj), align=8):
                node = ref - L.NODE_OBJ
                if mem.u32(node + L.NODE_KEY) != key:
                    continue
                for bref in mem.scan(struct.pack("<Q", node), align=8):
                    base = bref - (key % L.OBJTABLE_BUCKETS) * 8
                    t = cls(mem, base)
                    if t.lookup(oid) == obj and t.coverage(ids) >= 0.8:
                        log(f"object table at 0x{base:x}")
                        return t
        log(f"object table not found ({len(candidates)} candidate objects)")
        return None

    def coverage(self, ids, sample=40):
        """Fraction of the given object ids this table resolves (validates the table)."""
        ids = list(ids)[:sample]
        return sum(1 for i in ids if self.lookup(i)) / len(ids) if ids else 0.0


def _exo_list(mem, addr):
    b = mem.read(addr, 16)
    if not b:
        return 0, 0
    p, n, _cap = struct.unpack("<Qii", b)
    return p, max(0, min(n, 100000))


def area_ids(mem, area):
    p, n = _exo_list(mem, area + L.AREA_OBJECT_IDS)
    raw = mem.read(p, n * 4) if p and n else b""
    return struct.unpack(f"<{len(raw)//4}I", raw) if raw else ()


def vec3(mem, addr):
    b = mem.read(addr, 12)
    return struct.unpack("<fff", b) if b and len(b) == 12 else (0.0, 0.0, 0.0)


def map_pins(mem, area):
    vt = mem.base + L.VTABLES["CNWCMapPin"]
    p, n = _exo_list(mem, area + L.AREA_PINS)
    raw = mem.read(p, n * 8) if p and n else b""
    out = []
    for pin in struct.unpack(f"<{len(raw)//8}Q", raw) if raw else ():
        if mem.u64(pin) == vt:
            out.append({"kind": "pin", "name": mem.exostring(pin + L.PIN_TEXT), "tag": None,
                        "pos": vec3(mem, pin + L.OBJ_POS)})
    return out


def doors(mem, area, table):
    vt = mem.base + L.VTABLES["CNWCDoor"]
    out = []
    for oid in area_ids(mem, area):
        o = table.lookup(oid)
        if o and mem.u64(o) == vt:
            out.append({"kind": "door", "name": mem.exostring(o + L.DOOR_NAME),
                        "tag": mem.exostring(o + L.DOOR_TAG), "pos": vec3(mem, o + L.OBJ_POS)})
    return out
