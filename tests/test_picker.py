import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, picker as P  # noqa: E402


class PickerTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", tmp), mock.patch.object(P, "DATA_DIR", tmp),
                        mock.patch.object(P, "RECENT_FILE", tmp / "recent.json")]
        for p in self.patches:
            p.start()
        self.s = dbmod.Store("t.world")
        self.s.upsert_area("a1", "Market Square")
        self.s.upsert_poi("a1", "pin", "City Gates", None, 10, 10, 0)
        self.s.upsert_poi("a1", "door", "The Vineyard Nymph", "ad_wd_17", 20, 20, 0)

    def tearDown(self):
        self.s.close()
        for p in self.patches:
            p.stop()

    def type(self, pk, text):
        for ch in text:
            pk.handle(P.EV_CHAR, ord(ch))

    def test_search_select_pick_and_remember(self):
        pk = Picker = P.Picker(self.s)
        pk.start(has_destination=False)
        self.assertEqual(pk.results, [])
        self.type(pk, "gat")
        self.assertEqual([r["name"] for r in pk.results], ["City Gates"])
        action, pick = pk.handle(P.EV_KEY, P.VK_RETURN)
        self.assertEqual((action, pick["name"], pick["x"]), ("pick", "City Gates", 10))
        self.assertFalse(pk.open)
        Picker.start(has_destination=True)
        self.assertEqual([r["name"] for r in pk.results], ["Clear destination", "City Gates"])

    def test_navigation_backspace_escape(self):
        pk = P.Picker(self.s)
        pk.start(False)
        self.type(pk, "xx")
        self.assertEqual(pk.results, [])
        pk.handle(P.EV_KEY, P.VK_BACK)
        pk.handle(P.EV_KEY, P.VK_BACK)
        self.type(pk, "e")              # matches area, pin and door
        self.assertGreaterEqual(len(pk.results), 3)
        pk.handle(P.EV_KEY, P.VK_DOWN)
        pk.handle(P.EV_KEY, P.VK_DOWN)
        self.assertEqual(pk.sel, 2)
        pk.handle(P.EV_KEY, P.VK_UP)
        self.assertEqual(pk.sel, 1)
        self.assertEqual(pk.handle(P.EV_KEY, P.VK_ESCAPE), ("cancel", None))

    def test_clear(self):
        pk = P.Picker(self.s)
        pk.start(has_destination=True)
        self.assertEqual(pk.handle(P.EV_KEY, P.VK_RETURN), ("clear", None))


if __name__ == "__main__":
    unittest.main()
