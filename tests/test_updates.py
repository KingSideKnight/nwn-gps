"""Update check: once a day, only when on, never trusting the response for links."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import updates as U  # noqa: E402


class Newest(unittest.TestCase):
    def test_picks_highest_published_release(self):
        rel = [{"tag_name": "v0.1.4"}, {"tag_name": "v0.2.0", "draft": True}, {"tag_name": "v0.1.10"},
               {"tag_name": "nightly"}, {"tag_name": 5}, "junk"]
        self.assertEqual(U.newest(rel), (0, 1, 10))
        self.assertIsNone(U.newest({"message": "rate limited"}))

    def test_links_always_point_at_this_project(self):
        self.assertEqual(U.release_url("0.1.5"), "https://github.com/KingSideKnight/nwn-gps/releases/tag/v0.1.5")


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(U, "STATE_FILE", self.dir / "update.json"),
                        mock.patch.object(U, "DATA_DIR", self.dir),
                        mock.patch.object(U, "__version__", "0.1.4")]
        for p in self.patches:
            p.start()
        self.calls = 0

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def fetcher(self, result):
        def f():
            self.calls += 1
            if isinstance(result, Exception):
                raise result
            return result
        return f

    def test_off_never_asks(self):
        self.assertEqual(U.check({"check_updates": False}, fetcher=self.fetcher((9, 9, 9)))[0], "off")
        self.assertEqual(self.calls, 0)

    def test_new_release_is_reported_and_remembered_for_a_day(self):
        status, version, url = U.check({}, now=1000.0, fetcher=self.fetcher((0, 1, 5)))
        self.assertEqual((status, version), ("new", "0.1.5"))
        self.assertTrue(url.endswith("/tag/v0.1.5"))
        self.assertEqual(U.check({}, now=1000.0 + 3600, fetcher=self.fetcher((0, 1, 6)))[:2], ("new", "0.1.5"))
        self.assertEqual(self.calls, 1)                                  # no second request within a day
        self.assertEqual(U.available(current="0.1.4")[0], "0.1.5")       # what the in-game GPS reads
        self.assertIsNone(U.available(current="0.1.5"))

    def test_up_to_date(self):
        self.assertEqual(U.check({}, now=1000.0, fetcher=self.fetcher((0, 1, 4)))[0], "current")

    def test_offline_retries_in_an_hour(self):
        self.assertEqual(U.check({}, now=1000.0, fetcher=self.fetcher(OSError("offline")))[0], "failed")
        self.assertEqual(U.check({}, now=1000.0 + 1800, fetcher=self.fetcher((0, 1, 5)))[0], "later")
        self.assertEqual(U.check({}, now=1000.0 + 3700, fetcher=self.fetcher((0, 1, 5)))[0], "new")


if __name__ == "__main__":
    unittest.main()
