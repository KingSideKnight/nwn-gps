"""Importing friends' maps: no double counting, all or nothing, and undo."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, edges, share  # noqa: E402

JUMP = ("a1", (20, 20, 0), "a2", (30, 30, 0))       # a teleport seen once: not trusted for routing


class Imports(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(dbmod, "DATA_DIR", self.dir / "data")
        self.p.start()
        self.me = dbmod.Store("srv")
        self.me.upsert_area("a1", "Market", "t", 10, 10, visit=True)
        self.me.upsert_area("a2", "Docks", "t", 10, 10, visit=True)
        self.n = 0

    def tearDown(self):
        self.me.close()
        self.p.stop()

    def friend_map(self, source=None, extra=None):
        """A friend's export (its own random map id unless `source`), with the jump in it."""
        self.n += 1
        d = self.dir / f"friend{self.n}"
        with mock.patch.object(dbmod, "DATA_DIR", d):
            f = dbmod.Store("srv")
            if source:
                f.db.execute("UPDATE meta SET value=? WHERE key='source'", (source,))
            for a in ("a1", "a2", "a3"):
                f.upsert_area(a, a, "t", 10, 10, visit=True)
            f.add_transition(*JUMP, "S", "S", kind="jump", confirmed=False)
            f.upsert_poi("a3", "pin", f"Pier {self.n}", None, 40, 5, 0)
            f.add_transition("a2", (99, 50, 0), "a3", (1, 50, 0))
            if extra:
                extra(f)
            out = f.export(self.dir / f"nwn-gps-srv-2026-11-25_12{self.n:02}.sqlite", share=True)
            f.close()
        return out

    def jump(self):
        return self.me.db.execute("SELECT count, confirmed FROM transitions WHERE kind='jump'").fetchone()

    def test_same_file_twice_is_refused(self):
        f = self.friend_map()
        self.me.merge(f)
        with self.assertRaises(dbmod.AlreadyImported):
            self.me.merge(f)
        self.assertEqual(tuple(self.jump()), (1, 0))

    def test_one_friend_counts_once_however_many_exports(self):
        for _ in range(4):                                  # four different exports of the same map
            self.me.merge(self.friend_map(source="ab" * 8))
        self.assertEqual(tuple(self.jump()), (1, 0))        # still one sighting: not routable
        self.assertEqual(len(self.me.transitions()), 1)     # only the walked link a2 -> a3

    def test_separate_friends_are_separate_sightings(self):
        ids = [self.me.merge(self.friend_map())["import_id"] for _ in range(edges.JUMP_CONFIRM)]
        self.assertEqual(tuple(self.jump()), (edges.JUMP_CONFIRM, 1))   # three people saw it: trusted
        out = self.me.undo_import(ids[-1])
        self.assertEqual(out["links_untrusted"], 1)
        self.assertEqual(tuple(self.jump()), (edges.JUMP_CONFIRM - 1, 0))

    def test_your_own_map_coming_back_vouches_for_nothing(self):
        mine = self.me.export(self.dir / "mine-copy.sqlite", share=True)
        self.me.add_transition(*JUMP, "S", "S", kind="jump", confirmed=False)
        self.me.merge(self.friend_map(source=self.me.my_source()))
        self.assertEqual(tuple(self.jump()), (1, 0))
        self.assertTrue(mine.exists())

    def test_a_file_that_fails_halfway_leaves_nothing(self):
        f = self.friend_map()
        real, calls = dbmod.Store.add_transition, []

        def flaky(store, *a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("disk full")
            return real(store, *a, **k)
        before = self.me.stats()
        with mock.patch.object(dbmod.Store, "add_transition", flaky), self.assertRaises(RuntimeError):
            self.me.merge(f)
        self.assertEqual(self.me.stats(), before)
        self.assertEqual(self.me.imports(), [])
        self.me.merge(f)                                    # and it can be imported properly later
        self.assertEqual(len(self.me.imports()), 1)

    def test_undo_takes_out_what_the_file_added(self):
        before = self.me.stats()
        added = self.me.merge(self.friend_map(extra=lambda f: f.save_tiles("a3", "t", 1, 1, [[1, 0, 0]])))
        self.assertGreater(self.me.stats()["pois"], before["pois"])
        self.assertIsNotNone(self.me.tiles("a3"))
        out = self.me.undo_import(added["import_id"])
        self.assertEqual(self.me.stats(), before)
        self.assertIsNone(self.me.area("a3"))
        self.assertIsNone(self.me.tiles("a3"))
        self.assertTrue(Path(out["backup"]).exists())
        self.assertIsNone(self.me.undo_import(added["import_id"]))      # only once
        self.assertIsNotNone(self.me.imports()[0]["undone"])

    def test_undo_keeps_what_you_have_seen_yourself_since(self):
        iid = self.me.merge(self.friend_map())["import_id"]
        # you then walk the friend's link and visit the area yourself
        self.me.upsert_area("a3", "Pier", "t", 10, 10, visit=True)
        self.me.add_transition("a2", (99, 50, 0), "a3", (1, 50, 0))
        self.me.undo_import(iid)
        self.assertIsNotNone(self.me.area("a3"))
        self.assertEqual(len(self.me.transitions()), 1)
        self.assertEqual(self.me.stats()["pois"], 0)        # the friend's pin you never saw goes

    def test_undone_file_can_be_imported_again(self):
        f = self.friend_map()
        self.me.undo_import(self.me.merge(f)["import_id"])
        self.me.merge(f)
        self.assertEqual(tuple(self.jump()), (1, 0))

    def test_shared_exports_say_nothing_about_your_imports(self):
        self.me.merge(self.friend_map())
        out = self.me.export(self.dir / "share.sqlite", share=True)
        con = dbmod.open_untrusted(out)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM imports").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sightings").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM transitions WHERE import_id IS NOT NULL").fetchone()[0], 0)
            self.assertEqual(dbmod.file_source(con), self.me.my_source())     # only the random map id
        finally:
            con.close()


class InboxRepeats(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        sd = self.dir / "NWN GPS"
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", self.dir / "data"),
                        mock.patch.object(share, "INBOX", sd / "Inbox"),
                        mock.patch.object(share, "MERGED", sd / "Inbox" / "merged")]
        for p in self.patches:
            p.start()
        dbmod.Store("w.test").close()
        self.msgs = []
        self.jobs = share.Jobs("w.test", lambda text, kind: self.msgs.append((kind, text)))

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_same_file_sent_again_is_set_aside(self):
        share.ensure_folders()
        friend = dbmod.Store(path=self.dir / "friend.sqlite")
        friend.upsert_area("a2", "Docks", "t", 8, 8)
        friend.close()
        shutil.copy(self.dir / "friend.sqlite", share.INBOX / "friend.sqlite")
        self.jobs.import_inbox()
        self.jobs.thread.join(10)
        self.assertIn("Undo: Settings > Imported maps", self.msgs[-1][1])
        shutil.copy(self.dir / "friend.sqlite", share.INBOX / "friend again.sqlite")
        self.jobs.import_inbox()
        self.jobs.thread.join(10)
        self.assertIn("Already imported before: friend again.sqlite", self.msgs[-1][1])
        self.assertEqual(list(share.INBOX.glob("*.sqlite")), [])
        s = dbmod.Store("w.test")
        self.assertEqual(len(s.imports()), 1)
        s.close()


if __name__ == "__main__":
    unittest.main()
