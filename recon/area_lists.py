"""Inspect (ptr, int size, int cap) arrays inside the current CNWCArea and check
whether entries are object pointers (by vtable) or object ids.

Usage: python area_lists.py [start_off] [end_off]
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from nwngps.session import Session  # noqa: E402
from nwngps import layout as L  # noqa: E402

start = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x100
end = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x400
session = Session(log=lambda m: None)
session.poll()
mem = session.mem
if mem is None:
    sys.exit("game not running")
vt = {mem.base + int(v["vtable_rva"], 16): k
      for k, vs in json.loads((ROOT / "vtables.json").read_text())["classes"].items() for v in (vs or [])}
inn = session._internal()
area = mem.u64(mem.u64(inn + L.INTERNAL_MODULE) + L.MODULE_CURRENT_AREA)
print(f"area 0x{area:x}")
data = mem.read(area, end)
for o in range(start, end - 15, 8):
    p, n, cap = struct.unpack_from("<Qii", data, o)
    if not (0x10000 < p < 0x7FFFFFFFFFFF and 0 < n <= cap <= 100000):
        continue
    raw = mem.read(p, min(n, 64) * 8) or b""
    qs = struct.unpack(f"<{len(raw)//8}Q", raw)
    kinds = [vt.get(mem.u64(q) or 0, None) for q in qs]
    ds = struct.unpack(f"<{min(n,64)}I", raw[:min(n, 64) * 4]) if len(raw) >= min(n, 64) * 4 else ()
    print(f"+0x{o:03x} ptr=0x{p:x} size={n} cap={cap}")
    if any(kinds):
        from collections import Counter
        print("   as object ptrs:", dict(Counter(k for k in kinds if k)))
    else:
        print("   as u32:", " ".join(f"{d:08x}" for d in ds[:16]))
session.close()
