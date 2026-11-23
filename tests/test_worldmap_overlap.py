"""World map: areas joined by an edge mustn't end up stacked on top of each other."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import worldmap as WM  # noqa: E402


def world(placed):
    """placed: {area: ((x, y), (w, h))}, all in cluster 0."""
    w = WM.World()
    for a, (o, s) in placed.items():
        w.origin[a], w.size[a], w.cluster[a] = o, s, 0
    return w


class Slide(unittest.TestCase):
    def setUp(self):
        # hub H at (0,0) 100x100; F south of H; B joined only to H's west edge, but placed 35 m low
        # (arrival waypoint off along the edge) so it overlaps F.
        self.w = world({"H": ((0, 0), (100, 100)), "F": ((-100, -100), (200, 100)),
                        "B": ((-120, -35), (120, 120))})
        self.geo = {"H": [("B", (-120, -35), "y"), ("F", (-100, -100), "x")],
                    "F": [("H", (100, 100), "x"), ("X", (0, 0), "y")],
                    "B": [("H", (120, 35), "y")]}

    def test_dead_end_slides_along_its_edge_until_clear(self):
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.origin["B"], (-120, 0))                 # up 35 m, still on H's west edge
        self.assertEqual(self.w.slid, {"B": 35})
        self.assertLessEqual(min(WM.overlap(self.w, "B", "F")), WM.OVERLAP_TOL)
        self.assertGreaterEqual(WM.overlap(self.w, "B", "H")[1], WM.MIN_SHARED)
        self.assertEqual(self.w.origin["F"], (-100, -100))              # the crossroads didn't move

    def test_never_slides_off_its_neighbour(self):
        # H's west edge is only 8 m long: any position of B clear of F shares less than MIN_SHARED
        self.w.size["H"] = (100, 8)
        self.w.origin["B"], self.w.size["B"] = (-120, -35), (120, 30)
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.origin["B"], (-120, -35))
        self.assertEqual(self.w.slid, {})

    def test_area_joined_on_two_axes_stays(self):
        self.geo["B"].append(("Y", (0, 0), "x"))
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.origin["B"], (-120, -35))

    def test_small_overlaps_are_left_alone(self):
        self.w.origin["B"] = (-120, -1.5)
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.origin["B"], (-120, -1.5))


class Covered(unittest.TestCase):
    def test_pins_under_an_area_drawn_later_are_hidden(self):
        w = world({"A": ((0, 0), (100, 100)), "C": ((0, 90), (100, 100))})
        order = WM.draw_order(w, 0)
        self.assertTrue(WM.covered(w, order, "A", 50, 95))      # A's strip under C
        self.assertFalse(WM.covered(w, order, "A", 50, 50))
        self.assertFalse(WM.covered(w, order, "C", 50, 95))     # C is on top


if __name__ == "__main__":
    unittest.main()
