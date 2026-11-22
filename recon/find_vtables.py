"""Static: find vtable RVAs for MSVC x64 classes via RTTI.

TypeDescriptor name ".?AVName@@" -> CompleteObjectLocator (sig=1, offset=0,
pTypeDescriptor rva) -> vtable is the qword after the pointer to the COL.

Usage: python find_vtables.py <exe> [ClassName ...]   (writes vtables.json next to this script)
"""
import json
import struct
import sys
from pathlib import Path

DEFAULT = ["CNWCArea", "CNWCDoor", "CNWCTrigger", "CNWCMapPin", "CNWCCreature",
           "CNWCPlayer", "CNWCModule", "CNWCPlaceable", "CNWCObject", "CPanelAreaMap",
           "CGuiMapPin", "CGuiMapSurface", "CGuiAreaLoadscreen", "CNWCMessage", "CNWArea"]

exe = Path(sys.argv[1])
names = sys.argv[2:] or DEFAULT
data = exe.read_bytes()
pe = struct.unpack_from("<I", data, 0x3C)[0]
opt = pe + 24
image_base = struct.unpack_from("<Q", data, opt + 24)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
sec_off = opt + struct.unpack_from("<H", data, pe + 20)[0]
secs = {}
for i in range(nsec):
    o = sec_off + i * 40
    n = data[o:o + 8].rstrip(b"\0").decode()
    vs, va, rs, raw = struct.unpack_from("<IIII", data, o + 8)
    secs[n] = (va, vs, raw, rs)

def off2rva(off):
    for va, vs, raw, rs in secs.values():
        if raw <= off < raw + rs:
            return va + off - raw

rva2off = lambda rva: next(raw + rva - va for va, vs, raw, rs in secs.values() if va <= rva < va + max(vs, rs))

rd_va, rd_vs, rd_raw, rd_rs = secs[".rdata"]
rdata = data[rd_raw:rd_raw + rd_rs]
result = {}
for name in names:
    tag = f".?AV{name}@@".encode() + b"\0"
    pos = data.find(tag)
    if pos < 0:
        result[name] = None
        continue
    td_rva = off2rva(pos) - 0x10
    vtables = []
    # Scan .rdata for COLs referencing this TD
    needle = struct.pack("<I", td_rva)
    i = rdata.find(needle)
    while i >= 0:
        col = i - 12
        if col >= 0 and i % 4 == 0:
            sig, offset, cd, td = struct.unpack_from("<IIII", rdata, col)
            if sig == 1 and td == td_rva:
                col_rva = rd_va + col
                ptr = struct.pack("<Q", image_base + col_rva)
                j = rdata.find(ptr)
                while j >= 0:
                    vtables.append({"vtable_rva": hex(rd_va + j + 8), "this_offset": offset})
                    j = rdata.find(ptr, j + 1)
        i = rdata.find(needle, i + 1)
    result[name] = vtables
    print(f"{name:20} {vtables}")

out = Path(__file__).parent / "vtables.json"
out.write_text(json.dumps({"image_base": hex(image_base), "classes": result}, indent=2))
print("wrote", out)
