import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, worldmap  # noqa: E402


class WorldMapKinds(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp()))
        self.patch.start()
        self.st = dbmod.Store("w")
        for a in ("a", "b", "c", "fugue"):
            self.st.upsert_area(a, a, "t", 4, 4, visit=True, server="S")

    def tearDown(self):
        self.st.close()
        self.patch.stop()

    def test_walk_off_north_edge_places_areas(self):
        self.st.add_transition("a", (20, 39, 0), "b", (20, 1, 0), "S", "S")
        w = worldmap.build(self.st)
        self.assertEqual(w.origin["b"], (0.0, 40.0))

    def test_jumps_and_deaths_at_edges_place_nothing(self):
        self.st.add_transition("a", (20, 39, 0), "c", (20, 1, 0), "S", "S", kind="jump", confirmed=False)
        self.st.add_transition("a", (20, 1, 0), "fugue", (20, 39, 0), "S", "S", kind="death", confirmed=False)
        w = worldmap.build(self.st)
        self.assertNotIn("c", w.origin)
        self.assertNotIn("fugue", w.origin)
        self.assertEqual(w.interiors, [])

    def test_disagreeing_link_is_reported_and_the_busier_one_wins(self):
        for _ in range(3):
            self.st.add_transition("a", (20, 39, 0), "b", (20, 1, 0), "S", "S")     # b north of a
        self.st.add_transition("b", (39, 20, 0), "a", (1, 20, 0), "S", "S")         # says a east of b
        w = worldmap.build(self.st)
        self.assertEqual(w.origin["b"][1] - w.origin["a"][1], 40.0)
        self.assertTrue(w.conflicts)



class FullMapRefresh(unittest.TestCase):
    def test_picks_up_areas_the_recorder_adds_later(self):
        from nwngps.fullmap import FullMap
        with mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp())):
            st = dbmod.Store("w")
            st.upsert_area("a", "a", "t", 4, 4, visit=True, server="S")
            fm = FullMap(st, None)
            v1 = fm.refresh()
            self.assertNotIn("b", fm.world.origin)
            self.assertEqual(fm.refresh(), v1)                  # nothing new: no rebuild
            st.upsert_area("b", "b", "t", 4, 4, visit=True, server="S")   # recorder, a moment later
            st.add_transition("a", (20, 39, 0), "b", (20, 1, 0), "S", "S")
            self.assertNotEqual(fm.refresh(), v1)
            self.assertIn("b", fm.world.origin)
            st.close()


if __name__ == "__main__":
    unittest.main()
