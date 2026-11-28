"""Choosing routes by distance on foot: walking distances from one point to many exits, saved
per area layout and filled in the background; the router prefers the exit that's really
nearer on foot; a way that's blocked inside an area is a last resort; and a route only gives
way to a clearly shorter one, so near-equal routes don't take turns."""
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nwngps import db as dbmod, nav as N, route as R, walkmesh as W  # noqa: E402
from test_walkmesh import FakeRes  # noqa: E402

WALLED = ("tst01", 3, 1, [(0, 0, 0), (1, 0, 0), (0, 0, 0)])    # a wall at x = 15 with a gap at the north end
OPEN = ("tst01", 3, 1, [(0, 0, 0), (0, 0, 0), (0, 0, 0)])


def wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.01)
    return None


class Cached(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(W, "MAP_DIR", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def paths(self, fill=True):
        return W.Paths(log=lambda m: None, make_resources=lambda host: FakeRes(), fill=fill)


class Distances(Cached):
    def test_one_search_measures_every_exit(self):
        grid = W.Grids(FakeRes()).grid(*WALLED)
        d = W.distances(grid, (12.0, 2.0), [(18.0, 2.0), (8.0, 2.0), (12.0, 9.0)])
        self.assertAlmostEqual(d[(8.0, 2.0)], 4.0, delta=0.6)          # open ground: about the straight line
        self.assertGreater(d[(18.0, 2.0)], 13)                         # around the wall's north end
        path = W.find_path(grid, (12.0, 2.0), (18.0, 2.0))
        on_foot = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        self.assertLess(abs(d[(18.0, 2.0)] - on_foot), 1.5)            # agrees with the path you're shown
        self.assertGreaterEqual(d[(12.0, 9.0)], 7.0)                   # never shorter than straight

    def test_no_way_is_none(self):
        grid = W.Grids(FakeRes()).grid(*WALLED)
        grid[:, int(15 / W.CELL)] = False                              # close the gap
        d = W.distances(grid, (12.0, 2.0), [(18.0, 2.0)])
        self.assertIsNone(d[(18.0, 2.0)])

    def test_filled_in_the_background_saved_and_read_back(self):
        p = self.paths()
        self.assertIsNone(p.cost("a", (12.0, 2.0), (18.0, 2.0)))       # not known yet
        p.want_distances([("a", WALLED, [(12.0, 2.0), (2.0, 2.0)], [(18.0, 2.0), (2.0, 2.0)])])
        self.assertTrue(wait(lambda: p.cost("a", (2.0, 2.0), (18.0, 2.0)) and p.cost("a", (12.0, 2.0), (18.0, 2.0))))
        self.assertGreater(p.cost("a", (12.0, 2.0), (18.0, 2.0)), 13)
        self.assertTrue(wait(lambda: list(self.dir.glob("*.walkdist*"))))
        other = self.paths(fill=False)                                 # e.g. the map window: reads only
        other.want_distances([("a", WALLED, [(12.0, 2.0)], [(18.0, 2.0)])])
        self.assertTrue(wait(lambda: other.cost("a", (12.0, 2.0), (18.0, 2.0))))

    def test_a_changed_layout_is_worked_out_again(self):
        p = self.paths()
        p.want_distances([("a", WALLED, [(12.0, 2.0)], [(18.0, 2.0)])])
        self.assertTrue(wait(lambda: p.cost("a", (12.0, 2.0), (18.0, 2.0))))
        p.want_distances([("a", OPEN, [(12.0, 2.0)], [(18.0, 2.0)])])  # the server changed the area
        d = wait(lambda: (lambda v: v if v and v < 10 else None)(p.cost("a", (12.0, 2.0), (18.0, 2.0))))
        self.assertAlmostEqual(d, 6.0, delta=0.6)

    def test_damaged_table_files_are_ignored(self):
        path = W.dist_path(*WALLED)
        for junk in ("not json", '{"x": 1}', '{"1,2|3,4": "far"}', '{"1,2|3,4": -5}', '[1, 2]'):
            path.write_text(junk, encoding="utf-8")
            self.assertEqual(W.load_dists(path), {})

    def test_distances_from_you(self):
        p = self.paths()
        p.set_area("a", WALLED)
        p.want_here("a", (12.0, 2.0), [(18.0, 2.0), (8.0, 2.0)])
        self.assertTrue(wait(lambda: p.here_cost("a", (18.0, 2.0))))
        self.assertGreater(p.here_cost("a", (18.0, 2.0)), 13)
        self.assertIsNone(p.here_cost("b", (18.0, 2.0)))


def edge(frm, fxy, to, txy, **kw):
    return dict(from_area=frm, from_x=fxy[0], from_y=fxy[1], to_area=to, to_x=txy[0], to_y=txy[1], **kw)


class Router(unittest.TestCase):
    # Two exits from a to b: E1 is nearer in a straight line, E2 is nearer on foot.
    E1, E2 = edge("a", (18, 2), "b", (5, 5)), edge("a", (2, 2), "b", (5, 5))
    INDEX = {"a": [E1, E2]}

    def walk(self, table):
        return lambda area, frm, to, first: table.get((area, tuple(to)))

    def test_straight_lines_without_walking_distances(self):
        self.assertEqual(R.plan(None, "a", (12, 2), "b", index=self.INDEX), [self.E1])

    def test_the_exit_nearer_on_foot_wins(self):
        walk = self.walk({("a", (18, 2)): 16.0, ("a", (2, 2)): 10.0})
        self.assertEqual(R.plan(None, "a", (12, 2), "b", index=self.INDEX, walk=walk), [self.E2])

    def test_no_way_inside_the_area_is_a_last_resort(self):
        walk = self.walk({("a", (18, 2)): math.inf})
        self.assertEqual(R.plan(None, "a", (12, 2), "b", index=self.INDEX, walk=walk), [self.E2])
        only = {"a": [self.E1]}
        self.assertEqual(R.plan(None, "a", (12, 2), "b", index=only, walk=walk), [self.E1])   # still used
        self.assertAlmostEqual(R.route_cost([self.E1], "a", (12, 2), walk=walk), 6 + R.NO_WAY_COST + R.LOAD_COST)

    def test_route_cost_matches_the_plan(self):
        walk = self.walk({("a", (18, 2)): 16.0, ("a", (2, 2)): 10.0, ("b", (9, 8)): 7.0})
        steps = R.plan(None, "a", (12, 2), "b", goal_xy=(9, 8), index=self.INDEX, walk=walk)
        self.assertAlmostEqual(R.route_cost(steps, "a", (12, 2), (9, 8), walk), 10 + R.LOAD_COST + 7)
        self.assertIsNone(R.route_cost([self.E1], "b", (0, 0)))                # not a route from there


class FakePaths:
    """Walking distances the test sets by hand; anything else is the straight line (all known:
    plans are 'informed'). `at` is where you stand."""

    def __init__(self):
        self.table, self.at = {}, None

    def here_cost(self, area, to):
        return self.table.get((area, tuple(to)), math.dist(self.at, to) if self.at else None)

    def walk(self, *a):
        return None

    def cost(self, area, frm, to):
        return self.table.get((area, tuple(to)))

    def want_here(self, *a):
        pass

    def want_distances(self, *a):
        pass


def snap_at(area, x, y):
    return SimpleNamespace(state="IN_GAME", area=area, pos=(x, y, 0.0), facing=(0.0, 1.0, 0.0))


class NoFlipFlop(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp()))
        self.p.start()
        self.s = dbmod.Store("test.world")
        for a in ("a", "b", "c", "d"):
            self.s.upsert_area(a, a.upper())
        # Two ways from a to d: through b (exit at x=10) or through c (exit at x=90).
        self.s.add_transition("a", (10, 50, 0), "b", (5, 5, 0))
        self.s.add_transition("b", (95, 5, 0), "d", (50, 5, 0))
        self.s.add_transition("a", (90, 50, 0), "c", (5, 5, 0))
        self.s.add_transition("c", (95, 5, 0), "d", (50, 5, 0))
        self.paths = FakePaths()
        self.nav = N.Navigator(self.s, {"kind": "area", "area": "d", "name": "D", "x": None, "y": None}, self.paths)

    def tearDown(self):
        self.s.close()
        self.p.stop()

    def route_at(self, x):
        self.nav.plan_t = 0                                         # replan now
        self.paths.at = (x, 50)
        return self.nav.update(snap_at("a", x, 50)).target

    def test_near_equal_routes_dont_take_turns(self):
        self.assertEqual(self.route_at(45), (10, 50))               # b is a bit nearer
        self.assertEqual(self.route_at(52), (10, 50))               # now c is a bit nearer: stay
        self.assertEqual(self.route_at(56), (10, 50))
        self.assertEqual(self.route_at(80), (90, 50))               # clearly nearer: switch

    def test_a_walking_detour_switches_once_its_clearly_longer(self):
        self.assertEqual(self.route_at(45), (10, 50))
        self.paths.table[("a", (10, 50))] = 80.0                    # b's exit is a long walk round
        self.assertEqual(self.route_at(45), (90, 50))

    def test_a_first_guess_before_distances_are_known_can_change(self):
        unknown = FakePaths()
        unknown.here_cost = lambda area, to: None                   # distance from you not worked out yet
        nav = N.Navigator(self.s, {"kind": "area", "area": "d", "name": "D", "x": None, "y": None}, unknown)
        nav.update(snap_at("a", 45, 50))
        self.assertFalse(nav._informed)
        unknown.here_cost = lambda area, to: {(10, 50): 80.0}.get(tuple(to))
        nav.plan_t = 0
        self.assertEqual(nav.update(snap_at("a", 45, 50)).target, (90, 50))   # a small gain is enough


if __name__ == "__main__":
    unittest.main()
