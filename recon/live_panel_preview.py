"""Render the in-game panel from the live game state (with the tile map) to a PNG. Usage: python live_panel_preview.py <out.png>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps, panel  # noqa: E402
from nwngps.db import Store  # noqa: E402
from nwngps.resources import Resources  # noqa: E402
from nwngps.session import IN_GAME, Session  # noqa: E402

s = Session(log=lambda m: None)
for _ in range(100):
    snap = s.poll()
    if snap.state == IN_GAME:
        break
store = Store()
pois = store.db.execute("SELECT kind,name,x,y FROM pois WHERE area=?", (snap.area,)).fetchall()
tiles = maps.read_tiles(s.mem, snap.area_ptr, *snap.size)
img = maps.Maps(Resources()).image(snap.tileset, *snap.size, tiles)
panel.render(snap, None, pois, snap.size, img).save(sys.argv[1])
print(snap.area_name, snap.size, len(pois), "pois")
s.close()
