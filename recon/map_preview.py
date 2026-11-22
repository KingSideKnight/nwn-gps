"""Build the current area's map from tile art and save it, plus a copy rotated the other way
(to confirm the orientation direction visually). Usage: python map_preview.py <out_dir>"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps  # noqa: E402
from nwngps.resources import Resources  # noqa: E402
from nwngps.session import IN_GAME, Session  # noqa: E402

out = Path(sys.argv[1])
s = Session(log=lambda m: None)
for _ in range(100):
    snap = s.poll()
    if snap.state == IN_GAME:
        break
w, h = snap.size
tiles = maps.read_tiles(s.mem, snap.area_ptr, w, h)
print(snap.area, snap.area_name, snap.tileset, (w, h), "pos", snap.pos)
print("tiles:", tiles[:8], "...")
t = time.time()
M = maps.Maps(Resources())
img = M.image(snap.tileset, w, h, tiles)
print(f"built in {time.time() - t:.2f}s, ids known: {len(M.tileset(snap.tileset))}, "
      f"missing textures: {sum(1 for v in M.textures.values() if v is None)}")
scale = 8
big = img.resize((img.width * scale // 2, img.height * scale // 2), Image.NEAREST) if False else img
img.resize((img.width * 3, img.height * 3)).save(out / f"map_{snap.area}.png")
# alternative rotation direction for comparison
from PIL import Image  # noqa: E402
alt = Image.new("RGBA", img.size)
for i, (tid, o, _) in enumerate(tiles):
    tex = M.texture(M.tileset(snap.tileset).get(tid, "")) if tid in M.tileset(snap.tileset) else None
    if tex:
        alt.paste(tex.rotate(-90 * o), ((i % w) * 32, (h - 1 - i // w) * 32))
alt.resize((alt.width * 3, alt.height * 3)).save(out / f"map_{snap.area}_alt.png")
s.close()
