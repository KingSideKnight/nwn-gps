"""Render a sample GPS panel to a PNG (visual check without the game). Usage: python panel_preview.py <out.png>"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import panel  # noqa: E402
from nwngps.nav import Guidance  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402

s = Snapshot("IN_GAME", area="x", area_name="Cordor (Northern Outskirts)", server="ARE_CitiesAndPlanes",
             pos=(40, 160, 0), facing=(0, -1, 0), size=(15, 17))
g = Guidance("NAV", dest_name="The Vineyard Nymph [ad_wd_17]",
             line1='Take "City Gates" to Cordor (The Walled City) Government District',
             line2="Way back assumed (not walked yet)", target=(25, 10), distance=151, bearing=186, relative=6)
pois = [{"kind": "pin", "name": "City Gates", "x": 25, "y": 10},
        {"kind": "pin", "name": "Cordor Frontier", "x": 40, "y": 168},
        {"kind": "door", "name": "Door", "x": 80, "y": 60}]
t = time.time()
img = panel.render(s, g, pois, s.size)
print("render ms", round((time.time() - t) * 1000, 1), img.size, img.mode)
img.save(sys.argv[1])
