"""Breadth-first search from g_pAppManager for pointer chains to target addresses.

Usage: python pointer_path.py <target_hex> [<target_hex> ...] [--depth 5] [--span 0x400]
Prints chains like: g_pAppManager +0x8 -> +0x50 -> +0x1a0 = target
"""
import argparse
import struct
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps.memory import GameMemory  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("targets", nargs="+")
ap.add_argument("--depth", type=int, default=5)
ap.add_argument("--span", type=lambda s: int(s, 0), default=0x400)
ap.add_argument("--max-nodes", type=int, default=400000)
a = ap.parse_args()

mem = GameMemory()
targets = {int(t, 16): t for t in a.targets}
root = mem.u64(mem.base + 0x12DF970)  # g_pAppManager
q = deque([(root, ())])
seen = {root}
found = {}
nodes = 0
while q and nodes < a.max_nodes:
    addr, path = q.popleft()
    nodes += 1
    data = mem.read(addr, a.span)
    if not data:
        continue
    for o in range(0, len(data) - 7, 8):
        v = struct.unpack_from("<Q", data, o)[0]
        if v in targets:
            chain = path + (o,)
            found.setdefault(v, []).append(chain)
            if len(found[v]) <= 5:
                print(f"{targets[v]}: g_pAppManager " + " -> ".join(f"+0x{x:x}" for x in chain), flush=True)
        if len(path) + 1 < a.depth and 0x10000 < v < 0x7FFFFFFFFFFF and v % 8 == 0 and v not in seen:
            if not (mem.base <= v < mem.base + 0x1800000):
                seen.add(v)
                q.append((v, path + (o,)))
print(f"visited {nodes} nodes; found " + ", ".join(f"{targets[k]}:{len(v)}" for k, v in found.items()))
mem.close()
