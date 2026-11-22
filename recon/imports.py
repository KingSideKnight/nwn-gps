"""List a PE64's imported DLLs and selected functions. Usage: python imports.py <exe> [filter]"""
import re
import struct
import sys

data = open(sys.argv[1], "rb").read()
flt = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
pe = struct.unpack_from("<I", data, 0x3C)[0]
opt = pe + 24
nsec = struct.unpack_from("<H", data, pe + 6)[0]
so = opt + struct.unpack_from("<H", data, pe + 20)[0]
secs = [struct.unpack_from("<IIII", data, so + i * 40 + 8) for i in range(nsec)]
off = lambda rva: next(raw + rva - va for vs, va, rs, raw in secs if va <= rva < va + max(vs, rs))
imp = struct.unpack_from("<I", data, opt + 112 + 8)[0]
o = off(imp)
while True:
    ilt, _, _, name, iat = struct.unpack_from("<IIIII", data, o)
    if not name:
        break
    dll = data[off(name):data.index(b"\0", off(name))].decode()
    funcs = []
    p = off(ilt or iat)
    while True:
        e = struct.unpack_from("<Q", data, p)[0]
        if not e:
            break
        if not e >> 63:
            n = off(e & 0x7FFFFFFF) + 2
            funcs.append(data[n:data.index(b"\0", n)].decode())
        p += 8
    shown = [f for f in funcs if not flt or flt.search(f)]
    print(f"{dll}: {len(funcs)} imports" + (f"  -> {', '.join(shown)}" if flt and shown else ""))
    o += 20
