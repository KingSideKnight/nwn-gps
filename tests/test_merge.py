import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod  # noqa: E402


class Merge(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(dbmod, "DATA_DIR", self.dir)
        self.p.start()
        self.mine = dbmod.Store(path=self.dir / "mine.sqlite")
        self.theirs = dbmod.Store(path=self.dir / "theirs.sqlite")

    def tearDown(self):
        self.mine.close()
        self.p.stop()

    def test_merge_dedupes_and_fills_gaps(self):
        m, t = self.mine, self.theirs
        m.upsert_area("a1", "Market", "tcn01", None, None, visit=True)        # size unknown to me
        m.upsert_area("a2", "Gate")
        m.upsert_poi("a1", "pin", "Fountain", None, 10, 10, 0)
        m.add_transition("a1", (50, 99, 0), "a2", (50, 1, 0))
        t.upsert_area("a1", "Market", "tcn01", 10, 10)                         # they know the size
        t.upsert_area("a3", "Docks", "tno01", 8, 8)
        t.upsert_poi("a1", "pin", "Fountain", None, 11, 10.5, 0)              # same pin, 1 m away
        t.upsert_poi("a3", "pin", "Pier", None, 40, 5, 0)
        t.add_transition("a1", (51, 98, 0), "a2", (50, 2, 0))                 # same edge
        t.add_transition("a2", (99, 50, 0), "a3", (1, 50, 0))                 # new edge
        t.save_tiles("a3", "tno01", 8, 8, [[1, 0, 0]] * 64)
        t.close()
        added = m.merge(self.dir / "theirs.sqlite")
        self.assertEqual(added, {"areas": 1, "areas_updated": 1, "pois": 1, "transitions": 1,
                                 "transitions_seen_again": 1, "tile_layouts": 1, "gone_skipped": 0,
                             "rejected": 0, "import_id": 1})
        self.assertEqual((m.area("a1")["width"], m.area("a1")["visits"]), (10, 1))   # filled, my visits kept
        self.assertEqual(m.stats(), {"areas": 3, "pois": 2, "transitions": 2})
        self.assertIsNotNone(m.tiles("a3"))
        with self.assertRaises(dbmod.AlreadyImported):                       # the same file twice
            m.merge(self.dir / "theirs.sqlite")
        self.assertEqual(m.stats(), {"areas": 3, "pois": 2, "transitions": 2})

    def test_export_and_backup_are_full_copies(self):
        self.mine.upsert_area("a1", "Market")
        out = self.mine.export(self.dir / "share.sqlite")
        copy = dbmod.Store(path=out)
        self.assertEqual(copy.stats()["areas"], 1)
        copy.close()
        self.assertTrue(self.mine.backup("t").exists())

    def test_rejects_other_files(self):
        bad = self.dir / "x.sqlite"
        import sqlite3
        sqlite3.connect(bad).execute("CREATE TABLE foo(x)")
        with self.assertRaises(ValueError):
            self.mine.merge(bad)


if __name__ == "__main__":
    unittest.main()
