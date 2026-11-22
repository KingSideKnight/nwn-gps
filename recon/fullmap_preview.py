"""Render the full-screen map from the live game state. Usage: python fullmap_preview.py <out.png> [destination]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps  # noqa: E402
from nwngps.db import Store  # noqa: E402
from nwngps.fullmap import FullMap  # noqa: E402
from nwngps.nav import Navigator  # noqa: E402
from nwngps.resources import Resources  # noqa: E402
from nwngps.session import IN_GAME, Session  # noqa: E402

s = Session(log=lambda m: None)
for _ in range(100):
    snap = s.poll()
    if snap.state == IN_GAME:
        break
store = Store()
M = maps.Maps(Resources())
tiles = maps.read_tiles(s.mem, snap.area_ptr, *snap.size)
area_img = M.image(snap.tileset, *snap.size, tiles) if tiles else None
nav = g = None
if len(sys.argv) > 2:
    nav = Navigator(store, dict(store.search(sys.argv[2])[0]))
    g = nav.update(snap)
img = FullMap(store, M).render((1600, 900), snap, g, nav, area_img)
img.save(sys.argv[1])
print(snap.area_name, "->", g.line1 if g else "no destination")
s.close()
