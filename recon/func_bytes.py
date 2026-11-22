"""Print the first bytes of functions at given RVAs in nwmain.exe. Usage: python func_bytes.py <rva> [<rva>...] [--n 48]"""
import struct
import sys

EXE = r"D:\SteamLibrary\steamapps\common\Neverwinter Nights\bin\win32\nwmain.exe"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 48
data = open(EXE, "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
opt = pe + 24
nsec = struct.unpack_from("<H", data, pe + 6)[0]
so = opt + struct.unpack_from("<H", data, pe + 20)[0]
secs = [struct.unpack_from("<IIII", data, so + i * 40 + 8) for i in range(nsec)]
for a in args:
    rva = int(a, 16)
    off = next(raw + rva - va for vs, va, rs, raw in secs if va <= rva < va + max(vs, rs))
    print(f"{rva:08x}: {data[off:off + n].hex(' ')}")
