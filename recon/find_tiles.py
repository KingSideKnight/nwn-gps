"""Find the current area's tile array: a pointer in CNWCArea to w*h tiles where tile i has
x (+0x1C) = i % w and y (+0x20) = i // w. Tries contiguous arrays and pointer arrays."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import layout as L  # noqa: E402
from nwngps.session import IN_GAME, Session  # noqa: E402

TX, TY, TID, TH, TOR = 0x1C, 0x20, 0x14, 0x18, 0x24

s = Session(log=lambda m: None)
for _ in range(100):
    snap = s.poll()
    if snap.state == IN_GAME:
        break
m, area = s.mem, snap.area_ptr
w, h = snap.size
print(f"area {snap.area} {snap.area_name} size {w}x{h} at 0x{area:x}")
data = m.read(area, 0x800)


def check(get_tile):
    for i in (0, 1, w, w * h - 1):
        t = get_tile(i)
        if t is None or m.u32(t + TX) != i % w or m.u32(t + TY) != i // w:
            return False
    return True


for off in range(0, len(data) - 7, 8):
    p = struct.unpack_from("<Q", data, off)[0]
    if not 0x10000 < p < 0x7FFFFFFFFFFF:
        continue
    for stride in range(0x28, 0x400, 8):
        if check(lambda i: p + i * stride):
            print(f"contiguous tiles: area+0x{off:x} -> 0x{p:x}, stride 0x{stride:x}")
            break
    if check(lambda i: m.u64(p + i * 8)):
        print(f"pointer array of tiles: area+0x{off:x} -> 0x{p:x}")
        t0 = m.u64(p)
        vt = m.u64(t0)
        col = m.u64(vt - 8)
        print("   tile class:", m.cstr(m.base + m.u32(col + 12) + 0x10))
        for i in range(min(6, w * h)):
            t = m.u64(p + i * 8)
            print("   tile", i, "id", m.u32(t + TID), "xy", m.u32(t + TX), m.u32(t + TY),
                  "height", m.u32(t + TH), "orient", m.u32(t + TOR))
s.close()
