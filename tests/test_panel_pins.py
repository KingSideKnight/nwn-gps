"""The panel's follow window (areas over 120 m) must never hide that an area has pins."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import panel  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402


def snap(pos):
    return Snapshot("IN_GAME", t=0, world="w", server="S", module="m", area="a", area_name="A",
                    tileset="t", size=(18, 17), pos=pos, facing=(-1, 0, 0), area_ptr=0)


def gold_pixels(img, box):
    """Pin-gold pixels (labels are small antialiased text, so allow darker shades)."""
    crop = img.crop(box)
    px = crop.load()
    return sum(1 for x in range(crop.width) for y in range(crop.height)
               if (lambda r, g, b, a: r > 150 and 0.7 < g / r < 0.95 and b < 0.5 * r and a > 200)(*px[x, y]))


class FollowWindowPins(unittest.TestCase):
    MAP = (10, panel.MAP_Y + 10, 10 + panel.MAP_SIZE - 20, panel.MAP_Y + panel.MAP_SIZE - 10)

    def test_pins_outside_the_window_point_from_the_border(self):
        # standing on the east edge, the only pin is 150 m west: far outside the 120 m window
        img = panel.render(snap((176, 89, 0)), None, [{"kind": "pin", "name": "Far Away", "x": 20.0, "y": 89.0}],
                           (18, 17))
        x0, y0, x1, y1 = self.MAP
        self.assertGreater(gold_pixels(img, (x0, y0, x0 + 14, y1)), 5)       # pointer on the west border
        self.assertEqual(gold_pixels(img, (x0 + 14, y0, x1, y1)), 0)         # nothing drawn mid-map

    def test_label_at_the_right_edge_flips_left(self):
        def render(name):
            return panel.render(snap((170, 89, 0)), None, [{"kind": "pin", "name": name, "x": 176.6, "y": 89.1}],
                                (18, 17))
        x0, y0, x1, y1 = self.MAP
        box = (x1 - 120, y0, x1 - 20, y1)                  # left of the dot (which is ~6 px from the edge)
        a, b = render("Cordor Frontier").crop(box), render("").crop(box)
        pa, pb = a.load(), b.load()
        changed = sum(pa[x, y] != pb[x, y] for x in range(a.width) for y in range(a.height))
        self.assertGreater(changed, 50)                    # the label is drawn there, not off the edge

if __name__ == "__main__":
    unittest.main()
