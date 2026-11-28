"""Clicking a result in the picker: the click lands on the row drawn under it (also once the list
has scrolled), picks it like Enter, and does nothing while naming a place or between rows."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, panel, picker as P  # noqa: E402


def row_y(row):
    """A panel y in the middle of visible row `row`."""
    return panel.PICKER_TOP + row * panel.PICKER_ROW_H + 15


class Click(unittest.TestCase):
    HERE = {"area": "a1", "x": 33.0, "y": 44.0, "z": 0.0, "suggest": "Fountain"}

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", self.dir), mock.patch.object(P, "DATA_DIR", self.dir),
                        mock.patch.object(P, "RECENT_FILE", self.dir / "recent.json")]
        for p in self.patches:
            p.start()
        self.s = dbmod.Store(path=self.dir / "mine.sqlite")
        self.s.upsert_area("a1", "Market Square", "tcn01", 8, 8)
        for i in range(20):
            self.s.save_place("a1", i * 3, 70, f"Place {i:02}")
        self.pk = P.Picker(self.s)

    def tearDown(self):
        self.s.close()
        for p in self.patches:
            p.stop()

    def at(self, row, x=100):
        return panel.picker_row_at(self.pk, x, row_y(row))

    def test_click_picks_the_row_under_it(self):
        self.pk.start(False)
        self.assertEqual(self.at(2), 2)
        action, pick = self.pk.click(self.at(2))
        self.assertEqual((action, pick["name"]), ("pick", "Place 02"))
        self.assertFalse(self.pk.open)
        self.assertIsNone(self.pk.click(0))                          # closed: a late second click does nothing

    def test_rows_follow_the_scrolled_list(self):
        self.pk.start(False)
        for _ in range(15):
            self.pk.handle(P.EV_KEY, P.VK_DOWN)
        first = panel.picker_window(len(self.pk.results), self.pk.sel)
        self.assertGreater(first, 0)
        self.assertEqual(self.at(0), first)
        self.assertEqual(self.pk.click(self.at(4))[1]["name"], f"Place {first + 4:02}")

    def test_misses(self):
        self.pk.start(False)
        self.assertIsNone(panel.picker_row_at(self.pk, 100, 40))     # the search box
        self.assertIsNone(panel.picker_row_at(self.pk, 2, row_y(0)))  # the panel's edge
        self.assertIsNone(self.at(panel.PICKER_ROWS))                # below the last visible row
        self.assertIsNone(self.pk.click(None))
        self.assertTrue(self.pk.open)

    def test_short_list_has_no_rows_past_its_end(self):
        self.pk.start(False)
        for ch in "Place 05":
            self.pk.handle(P.EV_CHAR, ord(ch))
        n = len(self.pk.results)
        self.assertEqual(n, 1)
        self.assertEqual(self.at(n - 1), n - 1)
        self.assertIsNone(self.at(n))

    def test_clicking_save_asks_for_a_name_and_clicks_then_do_nothing(self):
        self.pk.start(False, here=self.HERE)
        self.assertEqual(self.pk.results[0]["kind"], "save_here")
        self.assertIsNone(self.pk.click(self.at(0)))                 # opens naming, still open
        self.assertTrue(self.pk.open and self.pk.naming)
        self.assertIsNone(panel.picker_row_at(self.pk, 100, row_y(1)))
        self.assertIsNone(self.pk.click(1))
        self.assertTrue(self.pk.naming)
        self.assertEqual(self.pk.handle(P.EV_KEY, P.VK_RETURN)[1]["name"], "Fountain")

    def test_a_click_forgets_a_first_delete(self):
        self.pk.start(False)
        self.pk.handle(P.EV_KEY, P.VK_DELETE)
        self.assertIsNotNone(self.pk.confirm)
        self.assertEqual(self.pk.click(self.at(1))[0], "pick")
        self.assertIsNone(self.pk.confirm)
        self.assertEqual(len(self.s.saved_places()), 20)


if __name__ == "__main__":
    unittest.main()
