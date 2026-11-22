"""Fetch a tileset .set through the resource reader and show its key lines. Usage: python read_set.py tno01"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps.resources import Resources  # noqa: E402

r = Resources()
name = sys.argv[1] if len(sys.argv) > 1 else "tno01"
data = r.get(name, "set")
if not data:
    sys.exit(f"{name}.set not found")
text = data.decode("latin-1")
print(f"{name}.set: {len(text)} chars")
print(text[:600])
tiles = re.findall(r"\[TILE(\d+)\]", text)
print("tiles:", len(tiles))
m = re.search(r"\[TILE0\](.*?)\n\[", text, re.S)
print("TILE0 block:\n", m.group(1)[:400] if m else None)
img = re.search(r"ImageMap2D=(\S+)", text)
if img:
    for ext in ("tga", "dds", "png"):
        d = r.get(img.group(1), ext)
        print(f"{img.group(1)}.{ext}:", len(d) if d else None, d[:18] if d else "")
