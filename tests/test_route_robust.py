"""Routes never lean on exits whose destination changes, and the map never draws a route
straight across areas it doesn't go through."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import route as R  # noqa: E402
from nwngps.fullmap import FullMap  # noqa: E402


def edge(a, ax, ay, b, bx, by, kind="walk", poi=None):
    return {"from_area": a, "from_x": ax, "from_y": ay, "to_area": b, "to_x": bx, "to_y": by,
            "kind": kind, "via_poi": poi}


# forest -> (long walk through a, b, c) -> city; and a shortcut through a portal hub whose one
# portal object has taken you to different places (it returns you where you entered).
LONG_WALK = [edge("forest", 10, 10, "a", 90, 10), edge("a", 10, 10, "b", 90, 10),
             edge("b", 10, 10, "c", 90, 10), edge("c", 10, 10, "city", 90, 10)]
HUB = [edge("hub", 50, 50, "forest", 60, 60, poi=7),          # the hub's portal once sent you to the forest
       edge("hub", 50, 51, "city", 40, 40, kind="portal", poi=7)]   # ... and once to the city


def areas(plan):
    return [t["to_area"] for t in plan]


class Ambiguous(unittest.TestCase):
    def test_an_exit_with_several_destinations_is_marked(self):
        edges = R.routable(HUB + LONG_WALK)
        self.assertTrue(all(e.get("ambiguous") for e in edges if e["from_area"] == "hub"))
        self.assertFalse(any(e.get("ambiguous") for e in edges if e["from_area"] != "hub"))

    def test_same_spot_without_an_object_counts_too(self):
        edges = R.routable([edge("hub", 50, 50, "x", 0, 0), edge("hub", 51, 50, "y", 0, 0),
                            edge("hub", 80, 80, "z", 0, 0)])
        self.assertEqual([bool(e.get("ambiguous")) for e in edges], [True, True, False])

    def test_two_doors_to_the_same_area_are_fine(self):
        edges = R.routable([edge("hall", 5, 5, "yard", 0, 0, poi=1), edge("hall", 6, 5, "yard", 3, 0, poi=1)])
        self.assertFalse(any(e.get("ambiguous") for e in edges))

    def test_the_route_walks_instead_of_using_the_hub(self):
        # the assumed way back from the forest into the hub would make the hub a big shortcut
        p = R.plan(HUB + LONG_WALK, "forest", (60, 60), "city")
        self.assertEqual(areas(p), ["a", "b", "c", "city"])
        self.assertFalse(any(t.get("ambiguous") or t["from_area"] == "hub" for t in p))

    def test_no_assumed_way_back_through_an_ambiguous_exit(self):
        edges = R.with_reverse_edges(HUB)
        self.assertFalse(any(e.get("assumed") and e["to_area"] == "hub" for e in edges))

    def test_the_hub_is_still_used_when_its_the_only_way(self):
        p = R.plan(HUB, "hub", (50, 50), "city")
        self.assertEqual(areas(p), ["city"])
        self.assertTrue(p[0]["ambiguous"])

    def test_shortest_path_from_where_you_stand(self):
        two_exits = [edge("square", 0, 0, "west", 100, 0), edge("square", 100, 0, "east", 0, 0),
                     edge("west", 0, 0, "inn", 0, 0), edge("east", 100, 0, "inn", 0, 0)]
        self.assertEqual(areas(R.plan(two_exits, "square", (5, 0), "inn"))[0], "west")
        self.assertEqual(areas(R.plan(two_exits, "square", (95, 0), "inn"))[0], "east")


class WayBack(unittest.TestCase):
    """A way back is assumed only where you came out next to a door, pin or the map edge."""
    PLACES = {"pois": {"forest": [(50, 50)]}, "sizes": {"forest": (16, 16), "plane": (10, 10)}}

    def assumed_into_plane(self, arrive_xy):
        e = edge("plane", 50, 50, "forest", *arrive_xy, poi=7)       # the plane's portal drops you here
        return any(r.get("assumed") for r in R.with_reverse_edges([e], self.PLACES))

    def test_dropped_mid_forest_no_way_back(self):
        self.assertFalse(self.assumed_into_plane((70, 90)))           # 20 m from the pin, 70 m from any edge

    def test_came_out_by_a_door_or_the_edge(self):
        self.assertTrue(self.assumed_into_plane((53, 50)))            # next to the door / pin
        self.assertTrue(self.assumed_into_plane((80, 157)))           # at the map edge (160 m area)

    def test_unknown_area_keeps_the_old_assumption(self):
        e = edge("plane", 50, 50, "unmapped", 70, 90)
        self.assertTrue(any(r.get("assumed") for r in R.with_reverse_edges([e], self.PLACES)))

    def test_without_places_nothing_changes(self):
        self.assertTrue(any(r.get("assumed") for r in R.with_reverse_edges([edge("a", 1, 1, "b", 70, 90)])))

    def test_route_from_the_forest_doesnt_walk_into_the_plane(self):
        portal = edge("plane", 50, 50, "forest", 70, 90, poi=7)
        city = edge("plane", 10, 10, "city", 5, 5)
        self.assertIsNone(R.plan([portal, city], "forest", (70, 90), "city", places=self.PLACES))


class RouteDrawing(unittest.TestCase):
    """FullMap._route_lines on a tiny world: areas a, b on the map, 'plane' (a portal hub) not on it,
    and 'isle' on another island of the map."""

    def setUp(self):
        fm = FullMap.__new__(FullMap)
        origin = {"a": (0, 0), "b": (100, 0), "isle": (5000, 0)}
        cluster = {"a": 0, "b": 0, "isle": 1}
        fm.world = SimpleNamespace(cluster=cluster, to_world=lambda home, x, y: (origin[home][0] + x, y))
        import nwngps.fullmap as F
        self._home_of = F.worldmap.home_of
        F.worldmap.home_of = lambda world, area: (area, None, None) if area in origin else (None, None, None)
        self.fm = fm

    def tearDown(self):
        import nwngps.fullmap as F
        F.worldmap.home_of = self._home_of

    def lines(self, plan, dest_area, goal=None):
        nav = SimpleNamespace(plan=plan, goal_xy=goal, dest={"area": dest_area})
        ident = lambda x, y: (x, y)          # noqa: E731
        return self.fm._route_lines(0, (5, 5), None, nav, ident, ident)

    def test_walking_route_is_one_line_through_each_exit(self):
        r = self.lines([edge("a", 90, 5, "b", 0, 5)], "b", goal=(50, 5))
        self.assertEqual(r["lines"], [[(5, 5), (90, 5), (100, 5), (150, 5)]])
        self.assertEqual(r["goal"], (150, 5))

    def test_line_stops_at_a_portal_and_resumes_after_it(self):
        r = self.lines([edge("a", 90, 5, "b", 20, 5, kind="portal"), edge("b", 60, 5, "a", 0, 0)], "a", goal=(1, 1))
        self.assertEqual(r["hops"], [(90, 5)])
        self.assertEqual(r["lines"], [[(5, 5), (90, 5)], [(120, 5), (160, 5), (0, 0), (1, 1)]])

    def test_no_line_across_a_place_not_on_the_map(self):
        r = self.lines([edge("a", 90, 5, "plane", 1, 1), edge("plane", 2, 2, "b", 30, 5)], "b", goal=(50, 5))
        self.assertEqual(r["lines"], [[(5, 5), (90, 5)], [(130, 5), (150, 5)]])
        for line in r["lines"]:
            self.assertNotIn(((90, 5), (130, 5)), list(zip(line, line[1:])))

    def test_no_line_onto_another_island(self):
        r = self.lines([edge("a", 90, 5, "isle", 1, 1)], "isle", goal=(9, 9))
        self.assertEqual(r["lines"], [[(5, 5), (90, 5)]])
        self.assertIsNone(r["goal"])


if __name__ == "__main__":
    unittest.main()
