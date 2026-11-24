"""World map: areas joined by an edge mustn't end up stacked on top of each other."""
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, worldmap as WM  # noqa: E402


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

    def test_never_slides_off_its_neighbour_but_is_pulled_clear(self):
        # H's west edge is only 8 m long: any position of B clear of F shares less than MIN_SHARED,
        # so B isn't slid; it is moved clear as a dead end instead (its join becomes a line)
        self.w.size["H"] = (100, 8)
        self.w.origin["B"], self.w.size["B"] = (-120, -35), (120, 30)
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.slid, {})
        self.assertIn("B", self.w.moved)
        self.assertEqual(WM._overlapping(self.w, ["H", "F", "B"]), [])
        self.assertEqual(self.w.origin["F"], (-100, -100))

    def test_area_joined_on_two_axes_isnt_slid_but_is_cleared(self):
        self.geo["B"].append(("Y", (0, 0), "x"))
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.slid, {})
        self.assertEqual(WM._overlapping(self.w, ["H", "F", "B"]), [])

    def test_small_overlaps_are_left_alone(self):
        self.w.origin["B"] = (-120, -1.5)
        WM._settle(self.w, self.geo, 0)
        self.assertEqual(self.w.origin["B"], (-120, -1.5))


class Separate(unittest.TestCase):
    """Overlaps no slide can clear (the world isn't flat)."""

    def setUp(self):
        self.patch = mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp()))
        self.patch.start()
        self.st = dbmod.Store("w")

    def tearDown(self):
        self.st.close()
        self.patch.stop()

    def area(self, a, w, h):
        self.st.upsert_area(a, a, "t", w, h, visit=True, server="S")

    def test_burial_grounds_under_earthkin_village(self):
        # Arelith, as recorded: Earthkin Village (190 x 170 m, a crossroads) south of Southern
        # Entrance; Ansrivarr Pond west of Southern Entrance; Burial Grounds south of the pond lands
        # on the village.
        for a, w, h in (("earthkin", 19, 17), ("entrance", 10, 10), ("pond", 9, 8), ("burial", 10, 10),
                        ("hunting", 10, 10), ("traders", 15, 15), ("riverbank", 15, 15)):
            self.area(a, w, h)
        self.st.add_transition("earthkin", (175, 165, 0), "entrance", (55, 2, 0), "S", "S")
        self.st.add_transition("traders", (95, 148, 0), "earthkin", (85, 4, 0), "S", "S")
        self.st.add_transition("earthkin", (188, 55, 0), "riverbank", (2, 105, 0), "S", "S")
        self.st.add_transition("entrance", (3, 49, 0), "pond", (86, 54, 0), "S", "S")
        self.st.add_transition("pond", (19, 1, 0), "burial", (40, 98, 0), "S", "S")
        self.st.add_transition("pond", (26, 78, 0), "hunting", (15, 3, 0), "S", "S")
        w = WM.build(self.st)
        members = WM.draw_order(w, 0)
        self.assertEqual(len(members), 7)
        self.assertEqual(WM._overlapping(w, members), [])
        self.assertEqual(w.overlaps, [])
        # one join was given up, the rest still sit side by side
        self.assertEqual(len(w.stretched), 1)
        for key in w.links:
            if key not in w.stretched:
                self.assertTrue(WM._side_by_side(w, *key), key)
        # the pond's chain moved as one piece: burial is still right under the pond
        self.assertTrue(WM._side_by_side(w, "pond", "burial"))
        self.assertTrue(WM._side_by_side(w, "pond", "hunting"))
        # the given-up join is drawn from its exit to its entry
        (a, pa, b, pb), = [w.links[k] for k in w.stretched]
        self.assertEqual(WM.join_lines(w, 0), [(w.to_world(a, *pa), w.to_world(b, *pb))])

    def test_small_overlap_in_a_loop_moves_one_area_a_little(self):
        # four areas in a ring whose links disagree by 9 m: no dead end to move
        w = world({"A": ((0, 0), (100, 100)), "B": ((100, 0), (100, 100)),
                   "C": ((100, 100), (100, 100)), "D": ((9, 91), (91, 100))})
        geo = {"A": [("B", None, "y"), ("D", None, "x")], "B": [("A", None, "y"), ("C", None, "x")],
               "C": [("B", None, "x"), ("D", None, "y")], "D": [("C", None, "y"), ("A", None, "x")]}
        WM._separate(w, geo, ["A", "B", "C", "D"])
        self.assertEqual(WM._overlapping(w, ["A", "B", "C", "D"]), [])
        (moved, (dx, dy)), = w.moved.items()
        self.assertLessEqual(abs(dx) + abs(dy), 10)

    def test_random_worlds_never_overlap(self):
        """Grow random trees of areas joined edge to edge, with arrival points off along the
        edge, and check the finished map never has two areas on top of each other."""
        rng = random.Random(7)
        for trial in range(40):
            self.tearDown()
            self.setUp()
            sizes = {f"a{i}": (rng.randint(4, 20), rng.randint(4, 20)) for i in range(rng.randint(4, 14))}
            for a, (w, h) in sizes.items():
                self.area(a, w, h)
            names = list(sizes)
            for i, b in enumerate(names[1:], 1):
                a = names[rng.randrange(i)]
                (wa, ha), (wb, hb) = [(x * 10, y * 10) for x, y in (sizes[a], sizes[b])]
                side = rng.choice("NSEW")
                ax = rng.uniform(5, wa - 5); ay = rng.uniform(5, ha - 5)
                bx = rng.uniform(5, wb - 5); by = rng.uniform(5, hb - 5)
                if side == "N":
                    ay, by = ha - 1, 1
                elif side == "S":
                    ay, by = 1, hb - 1
                elif side == "E":
                    ax, bx = wa - 1, 1
                else:
                    ax, bx = 1, wb - 1
                self.st.add_transition(a, (ax, ay, 0), b, (bx, by, 0), "S", "S")
            w = WM.build(self.st)
            for cid in set(w.cluster.values()):
                self.assertEqual(WM._overlapping(w, WM.draw_order(w, cid)), [], trial)


class Covered(unittest.TestCase):
    def test_pins_under_an_area_drawn_later_are_hidden(self):
        w = world({"A": ((0, 0), (100, 100)), "C": ((0, 90), (100, 100))})
        order = WM.draw_order(w, 0)
        self.assertTrue(WM.covered(w, order, "A", 50, 95))      # A's strip under C
        self.assertFalse(WM.covered(w, order, "A", 50, 50))
        self.assertFalse(WM.covered(w, order, "C", 50, 95))     # C is on top


if __name__ == "__main__":
    unittest.main()
