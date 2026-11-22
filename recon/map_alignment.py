"""Diagnose map alignment: draw recorded doors/pins and the player at their game positions over the
tile-art map at 4x (128 px per 10 m tile), with a 10 m grid. Usage: python map_alignment.py <out.png> [area_resref]"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps  # noqa: E402
from nwngps.db import Store  # noqa: E402
from nwngps.resources import Resources  # noqa: E402
from nwngps.session import IN_GAME, Session  # noqa: E402

S = 4                       # 32 px tile art -> 128 px per tile
s = Session(log=lambda m: None)
for _ in range(100):
    snap = s.poll()
    if snap.state == IN_GAME:
        break
store = Store()
area = sys.argv[2] if len(sys.argv) > 2 else snap.area
if area == snap.area:
    tileset, (w, h) = snap.tileset, snap.size
    tiles = maps.read_tiles(s.mem, snap.area_ptr, w, h)
else:
    tileset, w, h, tiles = store.tiles(area)
base = maps.Maps(Resources()).image(tileset, w, h, tiles).resize((w * 32 * S, h * 32 * S), Image.NEAREST)
img = Image.new("RGBA", base.size, (0, 0, 0, 255))
img.alpha_composite(base)
d = ImageDraw.Draw(img)
px_per_m = 32 * S / 10


def P(x, y):
    return x * px_per_m, (h * 10 - y) * px_per_m


for i in range(w + 1):
    d.line((i * 32 * S, 0, i * 32 * S, img.height), fill=(255, 255, 255, 60))
for j in range(h + 1):
    d.line((0, j * 32 * S, img.width, j * 32 * S), fill=(255, 255, 255, 60))
for p in store.db.execute("SELECT kind,name,x,y FROM pois WHERE area=?", (area,)):
    x, y = P(p["x"], p["y"])
    col = (255, 60, 60, 255) if p["kind"] == "door" else (255, 220, 0, 255)
    d.ellipse((x - 6, y - 6, x + 6, y + 6), outline=col, width=3)
    d.text((x + 8, y - 6), f"{p['name'][:14]} ({p['x']:.1f},{p['y']:.1f})", fill=col)
if area == snap.area and snap.pos:
    x, y = P(*snap.pos[:2])
    d.rectangle((x - 5, y - 5, x + 5, y + 5), fill=(0, 255, 255, 255))
    d.text((x + 8, y + 4), f"you ({snap.pos[0]:.1f},{snap.pos[1]:.1f})", fill=(0, 255, 255, 255))
img.save(sys.argv[1])
print(area, tileset, (w, h), "saved")
s.close()
