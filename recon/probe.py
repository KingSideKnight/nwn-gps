"""Live, read-only recon against a running nwmain.exe.

  python probe.py info                      process, base, build, globals
  python probe.py instances [Class ...]     find live objects by vtable
  python probe.py dump <addr> [len]         annotated dump of an object
  python probe.py strings <addr> [len]      strings reachable from an object
  python probe.py watch <addr> [len]        snapshot, you move, snapshot -> changed floats
  python probe.py findstr "<text>" [max]    find a string in memory + who points at it

Results are also appended to recon/out/probe_log.txt so we can read them later.
"""
import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from nwngps.memory import GameMemory  # noqa: E402

GAME = Path(r"D:\SteamLibrary\steamapps\common\Neverwinter Nights")
VT = json.loads((ROOT / "vtables.json").read_text())
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
LOG = open(OUT / "probe_log.txt", "a", encoding="utf-8")

# Exported globals (RVA) from dump_exports.py for build in vtables.json
GLOBALS = {"g_pAppManager": 0x12DF970, "g_pExoResMan": 0x12DF960, "g_pGuiMan": 0x12DF8B0,
           "g_pServerInfo": 0x12DF8D0, "g_pRules": 0x12DF8F8}


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


def vtable_map(mem):
    m = {}
    for cls, vts in VT["classes"].items():
        for v in vts or []:
            m[mem.base + int(v["vtable_rva"], 16)] = cls if v["this_offset"] == 0 else f"{cls}+{v['this_offset']}"
    return m


def printable(s):
    return s and len(s) >= 2 and all(32 <= ord(c) < 127 for c in s)


def describe_qword(mem, q, vtm):
    if q in vtm:
        return f"vtable {vtm[q]}"
    if mem.base <= q < mem.base + 0x1800000:
        return f"nwmain+0x{q - mem.base:x}"
    if 0x10000 < q < 0x7FFFFFFFFFFF:
        v = mem.u64(q)
        if v in vtm:
            return f"-> object {vtm[v]}"
        s = mem.cstr(q, 64)
        if printable(s):
            return f'-> "{s}"'
        if v is not None:
            return "-> ptr"
    return ""


def cmd_info(mem):
    out(f"pid={mem.pid} base=0x{mem.base:x} build={(GAME / 'bin/win32/build.txt').read_text().strip()!r}")
    for name, rva in GLOBALS.items():
        p = mem.u64(mem.base + rva)
        out(f"  {name:15} = 0x{p or 0:x}")
    am = mem.u64(mem.base + GLOBALS["g_pAppManager"])
    if am:
        out("CAppManager first fields:")
        cmd_dump(mem, am, 0x40)


def cmd_instances(mem, classes):
    vtm = vtable_map(mem)
    want = {k: v for k, v in vtm.items() if not classes or v.split("+")[0] in classes}
    pats = {struct.pack("<Q", k): v for k, v in want.items()}
    found = {}
    t = time.time()
    for p, addr in mem.scan_many(list(pats)):
        found.setdefault(pats[p], []).append(addr)
    out(f"scan took {time.time() - t:.1f}s")
    for cls in sorted(found):
        addrs = found[cls]
        out(f"{cls:20} {len(addrs):5}  " + " ".join(f"0x{a:x}" for a in addrs[:8]) + (" ..." if len(addrs) > 8 else ""))
    (OUT / "instances.json").write_text(json.dumps({k: [hex(a) for a in v] for k, v in found.items()}, indent=1))


def cmd_dump(mem, addr, length=0x200):
    vtm = vtable_map(mem)
    data = mem.read(addr, length) or b""
    for o in range(0, len(data) - 7, 8):
        q = struct.unpack_from("<Q", data, o)[0]
        f1, f2 = struct.unpack_from("<ff", data, o)
        i1, i2 = struct.unpack_from("<ii", data, o)
        fl = " ".join(f"{f:10.3f}" if 1e-3 < abs(f) < 1e6 else " " * 10 for f in (f1, f2))
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in data[o:o + 8])
        out(f"+{o:04x}  {q:016x}  {i1:11d} {i2:11d}  {fl}  {txt}  {describe_qword(mem, q, vtm)}")


def cmd_strings(mem, addr, length=0x800):
    data = mem.read(addr, length) or b""
    for o in range(0, len(data) - 7, 8):
        q = struct.unpack_from("<Q", data, o)[0]
        if 0x10000 < q < 0x7FFFFFFFFFFF:
            s = mem.cstr(q, 128)
            if printable(s):
                out(f"+{o:04x} -> {s!r}")
    # inline strings (e.g. CResRef = char[16] or [32])
    for chunk in data.split(b"\0"):
        if len(chunk) >= 4 and all(32 <= b < 127 for b in chunk):
            out(f"  inline: {chunk.decode()!r} @+{data.find(chunk):04x}")


def cmd_watch(mem, addr, length=0x1000):
    a = mem.read(addr, length)
    input("Snapshot taken. Now MOVE your character a few steps, then press Enter... ")
    b = mem.read(addr, length)
    out(f"changed 4-byte values in 0x{addr:x}[0:0x{length:x}]:")
    for o in range(0, min(len(a), len(b)) - 3, 4):
        if a[o:o + 4] != b[o:o + 4]:
            fa, fb = struct.unpack_from("<f", a, o)[0], struct.unpack_from("<f", b, o)[0]
            ia, ib = struct.unpack_from("<i", a, o)[0], struct.unpack_from("<i", b, o)[0]
            out(f"  +{o:04x}  float {fa:12.4f} -> {fb:12.4f}   int {ia} -> {ib}")


def cmd_findstr(mem, text, maxhits=10):
    pat = text.encode("latin-1")
    hits = []
    for a in mem.scan(pat):
        hits.append(a)
        if len(hits) >= maxhits:
            break
    out(f"{len(hits)} hits for {text!r}")
    vtm = vtable_map(mem)
    for h in hits:
        refs = []
        for r in mem.scan(struct.pack("<Q", h), align=8):
            refs.append(r)
            if len(refs) >= 5:
                break
        out(f"  0x{h:x} referenced from: " + ", ".join(f"0x{r:x}" for r in refs))
        for r in refs:
            # walk back up to 0x400 bytes looking for a known vtable = owning object
            back = mem.read(r - 0x400, 0x408) or b""
            for o in range(len(back) - 8, -1, -8):
                q = struct.unpack_from("<Q", back, o)[0]
                if q in vtm:
                    obj = r - 0x400 + o
                    out(f"     inside {vtm[q]} @0x{obj:x} at +0x{r - obj:x}")
                    break


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        mem = GameMemory()
    except RuntimeError as e:
        sys.exit(f"{e}. Start the game (and log into a character) first.")
    out(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {cmd} {' '.join(args)}")
    try:
        if cmd == "info":
            cmd_info(mem)
        elif cmd == "instances":
            cmd_instances(mem, args)
        elif cmd == "dump":
            cmd_dump(mem, int(args[0], 16), int(args[1], 16) if len(args) > 1 else 0x200)
        elif cmd == "strings":
            cmd_strings(mem, int(args[0], 16), int(args[1], 16) if len(args) > 1 else 0x800)
        elif cmd == "watch":
            cmd_watch(mem, int(args[0], 16), int(args[1], 16) if len(args) > 1 else 0x1000)
        elif cmd == "findstr":
            cmd_findstr(mem, args[0], int(args[1]) if len(args) > 1 else 10)
        else:
            print(__doc__)
    finally:
        mem.close()


if __name__ == "__main__":
    main()
