"""Render the panel for a synthetic large area (fake tile art with a coordinate grid) to check
follow mode, clamping at edges and alignment of pins with the art. Usage: python panel_follow_test.py <out_dir>"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import panel  # noqa: E402
from nwngps.nav import Guidance  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402

out = Path(sys.argv[1])
w, h = 30, 24                                   # 300 x 240 m area
art = Image.new("RGBA", (w * 32, h * 32), (40, 70, 40, 255))
ad = ImageDraw.Draw(art)
for i in range(w):
    for j in range(h):
        x, y = i * 32, (h - 1 - j) * 32
        ad.rectangle((x, y, x + 31, y + 31), outline=(80, 120, 80, 255))
        if (i + j) % 5 == 0:
            ad.rectangle((x + 14, y + 14, x + 18, y + 18), fill=(0, 200, 255, 255))   # "door art" at tile centre
pois = [{"kind": "pin", "name": f"Tile {i},{j}", "x": i * 10 + 5, "y": j * 10 + 5}
        for i in range(w) for j in range(h) if (i + j) % 5 == 0 and i % 3 == 0]
for name, pos in (("centre", (150, 120)), ("sw_corner", (8, 8)), ("ne_edge", (295, 200))):
    s = Snapshot("IN_GAME", area="big", area_name="Synthetic 30x24", server="TEST", pos=(*pos, 0), facing=(0, 1, 0),
                 size=(w, h))
    g = Guidance("NAV", dest_name="Test", line1="Go", target=(pos[0] + 30, pos[1] + 20), distance=36, bearing=56,
                 relative=56)
    panel.render(s, g, pois, (w, h), art).save(out / f"follow_{name}.png")
print("ok")
