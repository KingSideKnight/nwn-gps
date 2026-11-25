"""Dragging the mini map to look around, and the glide back to following you."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import ingame, panel  # noqa: E402

SNAP = SimpleNamespace(state="IN_GAME", area_name="Forest", area="f", pos=(160.0, 160.0, 0.0),
                       facing=(0, 1, 0), server="ARE_Surface", size=(32, 32))


class View(unittest.TestCase):
    def test_dragging_moves_the_view_like_paper(self):
        x, y = panel.pan_metres((60, 0))
        self.assertLess(x, 0)                       # map dragged right: you see what's west
        self.assertEqual(panel.pan_metres((0, 60))[1], -x)   # dragged down: north, same scale
        left, top, v = panel._view(SNAP, 320, 320, panel.pan_metres((60, -30)))
        self.assertAlmostEqual(left + v / 2, 160 + panel.pan_metres((60, -30))[0])
        self.assertAlmostEqual(top - v / 2, 160 + panel.pan_metres((60, -30))[1])

    def test_view_stays_inside_the_area(self):
        left, top, v = panel._view(SNAP, 320, 320, (10_000, -10_000))
        self.assertEqual((left, top), (320 - v, v))

    def test_small_areas_show_whole_and_dont_pan(self):
        self.assertEqual(panel._view(SNAP, 100, 100, (50, 50)), panel._view(SNAP, 100, 100))

    def test_renders_with_you_off_the_view(self):
        img = panel.render(SNAP, None, [], SNAP.size, None, pan=(400, 400))
        self.assertEqual(img.size, (panel.W, panel.H))


class SnapBack(unittest.TestCase):
    def test_follows_the_drag_then_glides_back(self):
        p = ingame.MapPan()
        self.assertEqual(p.update((0, 0), False, 0.0), (0, 0))
        self.assertFalse(p.active)
        self.assertEqual(p.update((80, -40), True, 1.0), (80, -40))
        self.assertTrue(p.active)
        self.assertEqual(p.update((80, -40), False, 1.0), (80, -40))      # let go: the glide starts
        half = p.update((80, -40), False, 1.0 + ingame.SNAP_BACK / 2)     # on the way back
        self.assertTrue(0 < half[0] < 80 and -40 < half[1] < 0)
        self.assertEqual(p.update((80, -40), False, 1.0 + ingame.SNAP_BACK), (0, 0))
        self.assertFalse(p.active)

    def test_grabbing_again_mid_glide_takes_over(self):
        p = ingame.MapPan()
        p.update((80, 0), True, 0.0)
        p.update((80, 0), False, 0.05)
        self.assertEqual(p.update((10, 5), True, 0.1), (10, 5))


class SharedMemory(unittest.TestCase):
    def test_offsets_match_the_dll(self):
        src = (Path(__file__).resolve().parent.parent / "native" / "nwngps_gl.c").read_text(encoding="utf-8")
        self.assertEqual(ingame.O_PANEL_DRAG, ingame.O_MAP_INPUT + 12)
        self.assertIn(f"panel_drag_y;          /* at offset {ingame.O_PANEL_DRAG} */", src)
        self.assertIn(f"panel_dragging;                     /* at offset {ingame.O_PANEL_DRAG + 8} */", src)
        self.assertEqual(ingame.O_MAP_RECT, ingame.O_PANEL_DRAG + 12)
        self.assertIn(f"map_rect[4];                        /* at offset {ingame.O_MAP_RECT} */", src)
        x, y, w, h = panel.MAP_RECT
        self.assertTrue(0 <= x and x + w <= panel.W and 0 <= y and y + h <= panel.H)


if __name__ == "__main__":
    unittest.main()
