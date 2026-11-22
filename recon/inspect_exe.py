"""Read-only inspection of nwmain.exe: architecture, debug/PDB info, and
strings that hint at class names (RTTI), networking and area handling.

Usage: python inspect_exe.py "<path to nwmain.exe>" [out_dir]
"""
import re
import struct
import sys
from pathlib import Path

exe = Path(sys.argv[1])
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "out"
out_dir.mkdir(exist_ok=True)
data = exe.read_bytes()

pe = struct.unpack_from("<I", data, 0x3C)[0]
machine, nsec = struct.unpack_from("<HH", data, pe + 4)
opt = pe + 24
magic = struct.unpack_from("<H", data, opt)[0]
is64 = magic == 0x20B
print(f"machine=0x{machine:x} {'PE32+ (64-bit)' if is64 else 'PE32'} sections={nsec}")
image_base = struct.unpack_from("<Q" if is64 else "<I", data, opt + 24)[0]
print(f"image base=0x{image_base:x}")

# Sections
sec_off = opt + struct.unpack_from("<H", data, pe + 20)[0]
sections = []
for i in range(nsec):
    o = sec_off + i * 40
    name = data[o:o + 8].rstrip(b"\0").decode(errors="replace")
    vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
    sections.append((name, va, vsize, raw, rsize))
    print(f"  {name:8} va=0x{va:08x} vsize=0x{vsize:08x} raw=0x{raw:08x}")

def rva_to_off(rva):
    for _, va, vs, raw, rs in sections:
        if va <= rva < va + max(vs, rs):
            return raw + rva - va
    return None

# Debug directory (index 6) -> CodeView PDB path
dd = opt + (112 if is64 else 96)
dbg_rva, dbg_size = struct.unpack_from("<II", data, dd + 6 * 8)
if dbg_rva:
    off = rva_to_off(dbg_rva)
    for i in range(dbg_size // 28):
        e = off + i * 28
        typ, size, _, ptr = struct.unpack_from("<IIII", data, e + 12)
        if typ == 2 and data[ptr:ptr + 4] == b"RSDS":
            pdb = data[ptr + 24:ptr + size].split(b"\0")[0].decode(errors="replace")
            print("PDB path:", pdb)

# Export count
exp_rva = struct.unpack_from("<I", data, dd)[0]
if exp_rva:
    eo = rva_to_off(exp_rva)
    nfun, nnames = struct.unpack_from("<II", data, eo + 20)
    print(f"exports: functions={nfun} names={nnames}")

# RTTI type descriptors: ".?AV<name>@@"
rtti = sorted(set(m.group(1).decode() for m in re.finditer(rb"\.\?A[VU]([A-Za-z0-9_@]+?)@@", data)))
print(f"RTTI class names: {len(rtti)}")
(out_dir / "rtti.txt").write_text("\n".join(rtti))

# ASCII strings of interest
strings = [m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{5,}", data)]
(out_dir / "strings.txt").write_text("\n".join(strings))
pat = re.compile(r"(?i)crypt|sodium|encrypt|handshake|areaload|area_|mapnote|map note|waypoint|transition|minimap|CNWCArea|CNWCMessage|HandleServerToPlayer")
hits = sorted(set(s for s in strings if pat.search(s)))
(out_dir / "interesting_strings.txt").write_text("\n".join(hits))
print(f"strings={len(strings)} interesting={len(hits)}")
area_classes = [c for c in rtti if re.search(r"(?i)area|map|waypoint|door|trigger|message|net|player|creature|crypt", c)]
print("relevant RTTI:", ", ".join(area_classes[:120]))
