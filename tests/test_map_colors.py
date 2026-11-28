"""The route line and your arrow get colours that stand out from the area's tile art: never the
art's own colour, never the same as each other, the usual ones when nothing beats them, and the
panel still draws without a map."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import panel  # noqa: E402
from nwngps.nav import Guidance  # noqa: E402


def art(color, size=(256, 256), patch=None):
    img = Image.new("RGBA", size, color)
    if patch:                                    # a small, eye-catching bit of another colour
        img.paste(Image.new("RGBA", (40, 40), patch), (10, 10))
    return img


class Colors(unittest.TestCase):
    def test_no_map_means_the_usual_colours(self):
        self.assertEqual(panel.map_colors(None), (panel.ROUTE, panel.ME))

    def test_the_same_art_always_gets_the_same_colours(self):
        a, b = panel.map_colors(art((128, 128, 128, 255))), panel.map_colors(art((128, 128, 128, 255)))
        self.assertEqual(a, b)
        self.assertIn(a[0], panel.ROUTE_COLORS)
        self.assertIn(a[1], panel.ME_COLORS)

    def test_never_the_colour_of_the_art(self):
        for ground in [(76, 217, 100, 255), (60, 190, 90, 255), (255, 70, 200, 255), (63, 193, 255, 255),
                       (250, 250, 250, 255), (255, 130, 60, 255)]:
            route, me = panel.map_colors(art(ground))
            self.assertNotEqual(route, me)
            for c in (route, me):
                self.assertGreater(sum(abs(a - b) for a, b in zip(c[:3], ground[:3])), 120, (ground, c))

    def test_small_bright_icons_count_too(self):
        route, me = panel.map_colors(art((128, 128, 128, 255), patch=panel.ROUTE))
        self.assertNotEqual(route, panel.ROUTE)

    def test_transparent_map_edges_are_ignored(self):
        img = art((0, 0, 0, 0))
        self.assertEqual(panel.map_colors(img), (panel.ROUTE, panel.ME))

    def test_panel_draws_with_and_without_art(self):
        snap = SimpleNamespace(state="IN_GAME", area="a1", area_name="Somewhere", pos=(20.0, 20.0, 0.0),
                               facing=(0.0, 1.0, 0.0), size=(4, 4), server="")
        g = Guidance("NAV", dest_name="X", line1="Go", target=(35.0, 35.0), distance=21.0, bearing=45.0,
                     relative=45.0, path=[(20.0, 20.0), (20.0, 35.0), (35.0, 35.0)])
        for img in (None, art((76, 217, 100, 255), size=(128, 128))):
            out = panel.render(snap, g, [], snap.size, img)
            self.assertEqual(out.size, (panel.W, panel.H))


if __name__ == "__main__":
    unittest.main()
