import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod  # noqa: E402
from nwngps.nav import Navigator, bearing  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402


def snap(area, pos, facing=(0, 1, 0)):
    return Snapshot("IN_GAME", area=area, pos=(*pos, 0.0), facing=facing, server="S")


class Nav(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp()))
        self.p.start()
        self.s = dbmod.Store("test.world")
        for a in ("a", "b"):
            self.s.upsert_area(a, a.upper())
        self.s.add_transition("a", (50, 100, 0), "b", (50, 0, 0))
        self.s.upsert_poi("b", "pin", "Shop", None, 80, 40, 0)

    def tearDown(self):
        self.s.close()
        self.p.stop()

    def dest(self):
        return self.s.search("Shop")[0]

    def test_bearings(self):
        self.assertEqual(bearing(0, 1), 0)
        self.assertEqual(bearing(1, 0), 90)
        self.assertEqual(bearing(0, -1), 180)
        self.assertEqual(bearing(-1, 0), 270)

    def test_points_at_exit_relative_to_facing(self):
        n = Navigator(self.s, self.dest())
        g = n.update(snap("a", (50, 50), facing=(1, 0, 0)))     # facing east, exit is north
        self.assertEqual(g.status, "NAV")
        self.assertEqual(g.target, (50, 100))
        self.assertAlmostEqual(g.distance, 50)
        self.assertAlmostEqual(g.relative, -90)                   # turn left
        self.assertIn("B", g.line1)

    def test_final_leg_and_arrival(self):
        n = Navigator(self.s, self.dest())
        g = n.update(snap("b", (50, 0)))
        self.assertEqual((g.status, g.target), ("NAV", (80, 40)))
        self.assertAlmostEqual(g.relative, bearing(30, 40))
        self.assertEqual(n.update(snap("b", (79, 39))).status, "ARRIVED")

    def test_not_in_game(self):
        g = Navigator(self.s, self.dest()).update(Snapshot("LOADING"))
        self.assertEqual((g.status, g.line1), ("WAITING", "Loading..."))


if __name__ == "__main__":
    unittest.main()
