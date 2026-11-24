"""Click to go: a click on the full map picks the marker or the spot under it."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, fullmap as F, worldmap as WM  # noqa: E402


class ClickToGo(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(dbmod, "DATA_DIR", self.dir)
        self.patch.start()
        self.store = dbmod.Store("click.test")
        self.store.upsert_area("a", "Town (Big) Market", "t", 10, 10)       # 100 x 100 m
        self.store.upsert_area("b", "Town (Big) Docks", "t", 10, 10)
        self.store.upsert_poi("b", "pin", "Bank", None, 30, 40, 0)
        self.m = F.FullMap(self.store, None)
        self.m.world = WM.World(origin={"a": (0, 0), "b": (100, 0)}, size={"a": (100, 100), "b": (100, 100)},
                                cluster={"a": 0, "b": 0})
        self.m.refresh = lambda: None                                       # keep the world above
        snap = SimpleNamespace(area="a", pos=(50, 50, 0), facing=(0, 1, 0), area_name="Market", size=(10, 10))
        self.m.render((1600, 900), snap, None, None, None)

    def tearDown(self):
        self.store.close()
        self.patch.stop()

    def pin_px(self):
        (px, py, dest), = self.m.clickable["hits"]
        self.assertEqual(dest["name"], "Bank")
        return px, py

    def test_click_near_a_pin_picks_the_pin(self):
        px, py = self.pin_px()
        pick = self.m.pick_at(px + 5, py - 4)
        self.assertEqual((pick["kind"], pick["area"], pick["name"], pick["x"], pick["y"]), ("pin", "b", "Bank", 30, 40))

    def test_click_on_open_ground_picks_that_spot(self):
        px, py = self.pin_px()
        area, x, y = self.m.clickable["spot"](px, py)                     # pixel -> area coordinates
        self.assertEqual(area, "b")
        self.assertAlmostEqual(x, 30, delta=0.5)
        self.assertAlmostEqual(y, 40, delta=0.5)
        pick = self.m.pick_at(px - 4 * F.HIT_RADIUS, py)                  # further west, still in an area
        self.assertEqual(pick["kind"], "spot")
        self.assertTrue(pick["name"].startswith("Spot in "))
        self.assertLess(pick["x"], 30)

    def test_click_off_the_map_picks_nothing(self):
        self.assertIsNone(self.m.pick_at(2, 2))                            # header corner
        self.assertIsNone(F.FullMap(self.store, None).pick_at(500, 500))  # nothing drawn yet

    def test_area_at_prefers_the_area_drawn_on_top(self):
        w = WM.World(origin={"x": (0, 0), "y": (50, 0)}, size={"x": (100, 100), "y": (100, 100)},
                     cluster={"x": 0, "y": 0})
        self.assertEqual(WM.area_at(w, 0, 75, 50), "y")
        self.assertEqual(WM.area_at(w, 0, 10, 50), "x")
        self.assertIsNone(WM.area_at(w, 0, 500, 50))


if __name__ == "__main__":
    unittest.main()
