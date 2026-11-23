import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import route as R  # noqa: E402


def edge(a, fx, fy, b, tx, ty, kind="walk"):
    return {"from_area": a, "from_x": fx, "from_y": fy, "to_area": b, "to_x": tx, "to_y": ty,
            "from_server": "S1", "to_server": "S2" if kind == "portal" else "S1", "kind": kind, "via_poi": None}


class Routing(unittest.TestCase):
    def test_forward_chain(self):
        steps = R.plan([edge("a", 10, 0, "b", 0, 0), edge("b", 50, 50, "c", 5, 5)], "a", (0, 0), "c")
        self.assertEqual([s["to_area"] for s in steps], ["b", "c"])
        self.assertFalse(any(s.get("assumed") for s in steps))

    def test_reverse_is_assumed_when_never_walked(self):
        steps = R.plan([edge("a", 10, 0, "b", 0, 0)], "b", (1, 1), "a")
        self.assertEqual(len(steps), 1)
        self.assertTrue(steps[0]["assumed"])
        self.assertEqual((steps[0]["from_x"], steps[0]["to_x"]), (0, 10))

    def test_walked_reverse_suppresses_assumed_one(self):
        steps = R.plan([edge("a", 10, 0, "b", 0, 0), edge("b", 1, 0, "a", 11, 0)], "b", (1, 1), "a")
        self.assertFalse(steps[0].get("assumed"))

    def test_assumed_reverse_can_be_disabled(self):
        self.assertIsNone(R.plan([edge("a", 10, 0, "b", 0, 0)], "b", (1, 1), "a", assume_reverse=False))

    def test_prefers_short_walk_over_extra_load(self):
        es = [edge("a", 100, 0, "c", 0, 0), edge("a", 1, 0, "b", 0, 0), edge("b", 1, 0, "c", 0, 0)]
        steps = R.plan(es, "a", (0, 0), "c")
        self.assertEqual([s["to_area"] for s in steps], ["b", "c"])


if __name__ == "__main__":
    unittest.main()


class KindRules(unittest.TestCase):
    def test_no_assumed_way_back_for_jumps_or_respawns(self):
        for kind in ("jump", "respawn"):
            es = [edge("a", 5, 5, "b", 5, 5, kind)]
            self.assertIsNotNone(R.plan(es, "a", (5, 5), "b"))
            self.assertIsNone(R.plan(es, "b", (5, 5), "a"), kind)

    def test_death_links_are_never_used(self):
        es = [edge("a", 5, 5, "fugue", 5, 5, "death")]
        self.assertIsNone(R.plan(es, "a", (5, 5), "fugue"))
        self.assertIsNone(R.plan(es, "fugue", (5, 5), "a"))

    def test_walk_still_gets_a_way_back(self):
        self.assertIsNotNone(R.plan([edge("a", 5, 5, "b", 5, 5)], "b", (5, 5), "a"))
