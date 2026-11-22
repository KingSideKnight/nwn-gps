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


if __name__ == "__main__":
    unittest.main()
