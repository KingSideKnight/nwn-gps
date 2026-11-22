"""Panel with a toast and the two legend rows. Usage: python panel_toast_preview.py <out.png>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import panel  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402

s = Snapshot("IN_GAME", area="x", area_name="Cordor (Northern Outskirts)", server="ARE_CitiesAndPlanes",
             pos=(40, 60, 0), facing=(0, 1, 0), size=(8, 8))
pois = [{"kind": "pin", "name": "City Gates", "x": 25, "y": 10}]
panel.render(s, None, pois, s.size, toast=("Imported: +120 areas, +3,400 places, +410 routes, +118 maps", "ok"),
             inbox=0).save(sys.argv[1])
