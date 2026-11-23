"""Scrolling and zooming the full-screen map (view logic only; the DLL feeds drag / wheel / keys)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import fullmap as F, worldmap as WM  # noqa: E402

ASPECT = 2.0


def fm(width=4000, height=2000):
    m = F.FullMap(None, None)
    m.world = WM.World(origin={"a": (0, 0)}, size={"a": (width, height)}, cluster={"a": 0})
    return m


def view(m, here=(500, 500)):
    v = m._view(0, here, ASPECT)
    m.last_view, m.last_px_per_m = v, 1000 / (v[2] - v[0])       # a 1000 px wide box
    return v


def center(v):
    return ((v[0] + v[2]) / 2, (v[1] + v[3]) / 2)


class Scroll(unittest.TestCase):
    def test_follows_you_by_default(self):
        m = fm()
        self.assertEqual(center(view(m, (2000, 1000))), (2000, 1000))
        self.assertEqual(view(m)[2] - view(m)[0], F.MAX_VIEW)

    def test_drag_moves_the_map_with_the_mouse(self):
        m = fm()
        view(m, (2000, 1000))
        m.drag(100, 50)                       # mouse right + down: you look further west + north
        cx, cy = center(view(m, (2000, 1000)))
        per_px = F.MAX_VIEW / 1000
        self.assertAlmostEqual(cx, 2000 - 100 * per_px)
        self.assertAlmostEqual(cy, 1000 + 50 * per_px)
        self.assertEqual(center(view(m, (3000, 1500)))[0], cx)       # walking no longer moves it

    def test_arrows_and_home(self):
        m = fm()
        view(m, (2000, 1000))
        m.pan(1, 0)
        self.assertAlmostEqual(center(view(m, (2000, 1000)))[0], 2000 + F.PAN_STEP * F.MAX_VIEW)
        m.reset_view()
        self.assertEqual(center(view(m, (2100, 1000))), (2100, 1000))

    def test_zoom_is_limited(self):
        m = fm()
        view(m)
        for _ in range(30):
            m.zoom(1)
            view(m)
        self.assertEqual(view(m)[2] - view(m)[0], F.MIN_SPAN)
        for _ in range(30):
            m.zoom(-1)
            view(m)
        self.assertEqual(view(m)[2] - view(m)[0], 4000)              # whole map, no further
        m.zoom(1)                                                      # one step back in works at once
        self.assertLess(view(m)[2] - view(m)[0], 4000)

    def test_cant_scroll_off_the_map(self):
        m = fm()
        view(m)
        for _ in range(50):
            m.pan(-1, -1)
            view(m)
        x0, y0, _, _ = view(m)
        self.assertEqual((x0, y0), (0, 0))

    def test_small_map_still_shows_whole_until_scrolled(self):
        m = fm(800, 400)
        self.assertEqual(view(m), (0, 0, 800, 400))


if __name__ == "__main__":
    unittest.main()
