"""Print areas (size, tiles saved) and transitions with how close each end is to an area edge."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps.db import Store  # noqa: E402

s = Store()
areas = {r["resref"]: r for r in s.db.execute("SELECT * FROM areas")}
tiles = {r["resref"] for r in s.db.execute("SELECT resref FROM area_tiles")}
for a in areas.values():
    print(f"{a['resref']:18} {a['width']}x{a['height']} tiles={'Y' if a['resref'] in tiles else '-'} "
          f"{a['server']:20} {a['name']}")


def edge(area, x, y):
    a = areas.get(area)
    if not a or not a["width"]:
        return "?"
    w, h = a["width"] * 10, a["height"] * 10
    d = {"W": x, "E": w - x, "S": y, "N": h - y}
    k = min(d, key=d.get)
    return f"{k}{d[k]:.0f}"


for t in s.transitions(include_unconfirmed=True):
    print(f"{t['kind']:6} {t['from_area']:18} ({t['from_x']:6.1f},{t['from_y']:6.1f}) {edge(t['from_area'], t['from_x'], t['from_y']):>4}"
          f"  -> {t['to_area']:18} ({t['to_x']:6.1f},{t['to_y']:6.1f}) {edge(t['to_area'], t['to_x'], t['to_y']):>4}")
s.close()
