import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, share  # noqa: E402


class ShareJobs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        sd = self.dir / "NWN GPS"
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", self.dir / "data"),
                        mock.patch.object(share, "EXPORTS", sd / "Exports"),
                        mock.patch.object(share, "INBOX", sd / "Inbox"),
                        mock.patch.object(share, "MERGED", sd / "Inbox" / "merged")]
        for p in self.patches:
            p.start()
        s = dbmod.Store("w.test")
        s.upsert_area("a1", "Market", "t", 10, 10)
        s.close()
        self.msgs = []
        self.jobs = share.Jobs("w.test", lambda text, kind: self.msgs.append((kind, text)))

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def wait(self):
        self.jobs.thread.join(10)

    def test_export_writes_file_and_reports(self):
        self.jobs.export()
        self.wait()
        files = list(share.EXPORTS.glob("*.sqlite"))
        self.assertEqual(len(files), 1)
        self.assertEqual(self.msgs[-1][0], "ok")
        self.assertIn("1 areas", self.msgs[-1][1])

    def test_import_merges_moves_and_backs_up(self):
        share.ensure_folders()
        friend = dbmod.Store(path=share.INBOX / "friend.sqlite")
        friend.upsert_area("a2", "Docks", "t", 8, 8)
        friend.close()
        sqlite3.connect(share.INBOX / "junk.sqlite").execute("CREATE TABLE x(y)")
        self.jobs.import_inbox()
        self.wait()
        kind, text = self.msgs[-1]
        self.assertEqual(kind, "warn")                       # junk file reported
        self.assertIn("+1 areas", text)
        self.assertIn("junk.sqlite", text)
        self.assertTrue((share.MERGED / "friend.sqlite").exists())
        self.assertTrue((share.INBOX / "junk.sqlite").exists())          # left for the player to look at
        self.assertTrue(list((self.dir / "data" / "backups").glob("*before-import*")))
        s = dbmod.Store("w.test")
        self.assertIsNotNone(s.area("a2"))
        s.close()

    def test_empty_inbox_explains_where_to_put_files(self):
        self.jobs.import_inbox()
        self.wait()
        self.assertIn("Inbox", self.msgs[-1][1])

    def friend_map(self, world, name):
        """A friend's export of `world`'s map, saved into the Inbox as `name`."""
        share.ensure_folders()
        f = dbmod.Store(world)
        f.upsert_area("z9", "Elsewhere", "t", 8, 8)
        dest = share.INBOX / name
        f.export(dest, share=True)
        f.close()
        return dest

    def test_export_is_tagged_with_its_server(self):
        self.jobs.export()
        self.wait()
        f = next(share.EXPORTS.glob("*.sqlite"))
        con = dbmod.open_untrusted(f)
        self.assertEqual(dbmod.file_world(con, "renamed.sqlite"), "w_test")
        con.close()

    def test_other_servers_map_is_left_in_the_inbox(self):
        theirs = self.friend_map("other.server", "from-bob.sqlite")
        self.jobs.import_inbox()
        self.wait()
        kind, text = self.msgs[-1]
        self.assertEqual(kind, "warn")
        self.assertIn("from-bob.sqlite (other_server)", text)
        self.assertTrue(theirs.exists())                              # kept for when you're on that server
        s = dbmod.Store("w.test")
        self.assertIsNone(s.area("z9"))                               # nothing merged
        s.close()

    def test_same_servers_map_still_imports(self):
        self.friend_map("w.test", "from-ann.sqlite")
        self.jobs.import_inbox()
        self.wait()
        self.assertEqual(self.msgs[-1][0], "ok")
        self.assertTrue((share.MERGED / "from-ann.sqlite").exists())

    def test_old_untagged_export_is_judged_by_its_file_name(self):
        p = self.friend_map("other.server", "x.sqlite")
        con = sqlite3.connect(p)
        con.execute("DROP TABLE meta")                                # as written by 0.1.4 and older
        con.commit()
        con.close()
        p.rename(share.INBOX / "nwn-gps-other_server-2026-11-20_2130.sqlite")
        self.jobs.import_inbox()
        self.wait()
        self.assertIn("Another server's map", self.msgs[-1][1])


if __name__ == "__main__":
    unittest.main()
