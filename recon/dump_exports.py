"""Dump named exports (name + RVA) of a PE64 file, demangled when possible.

Usage: python dump_exports.py <exe> <out_file>
"""
import ctypes
import struct
import sys

exe, out = sys.argv[1], sys.argv[2]
data = open(exe, "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
opt = pe + 24
nsec = struct.unpack_from("<H", data, pe + 6)[0]
sec_off = opt + struct.unpack_from("<H", data, pe + 20)[0]
secs = [struct.unpack_from("<IIII", data, sec_off + i * 40 + 8) for i in range(nsec)]

def off(rva):
    for vs, va, rs, raw in secs:
        if va <= rva < va + max(vs, rs):
            return raw + rva - va
    raise ValueError(hex(rva))

exp_rva = struct.unpack_from("<I", data, opt + 112)[0]
e = off(exp_rva)
nfun, nnames, afun, anames, aords = struct.unpack_from("<IIIII", data, e + 20)
funcs = [struct.unpack_from("<I", data, off(afun) + 4 * i)[0] for i in range(nfun)]

try:
    und = ctypes.windll.dbghelp.UnDecorateSymbolName
    und.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32]
except Exception:
    und = None

def demangle(name):
    if und and name.startswith("?"):
        buf = ctypes.create_string_buffer(2048)
        if und(name.encode(), buf, 2048, 0):
            return buf.value.decode(errors="replace")
    return name

rows = []
for i in range(nnames):
    nrva = struct.unpack_from("<I", data, off(anames) + 4 * i)[0]
    o = off(nrva)
    name = data[o:data.index(b"\0", o)].decode(errors="replace")
    ordi = struct.unpack_from("<H", data, off(aords) + 2 * i)[0]
    rows.append((funcs[ordi], name, demangle(name)))
rows.sort()
with open(out, "w", encoding="utf-8") as f:
    for rva, name, dem in rows:
        f.write(f"{rva:08x}\t{dem}\t{name}\n")
print(f"wrote {len(rows)} exports to {out}")
