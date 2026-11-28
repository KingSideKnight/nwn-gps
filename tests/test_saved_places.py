"""Saved places: storing them, finding them, the picker rows that save and remove them, and keeping
them out of exits, shared maps and other players' imports."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, panel, picker as P  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", self.dir), mock.patch.object(P, "DATA_DIR", self.dir),
                        mock.patch.object(P, "RECENT_FILE", self.dir / "recent.json")]
        for p in self.patches:
            p.start()
        self.s = dbmod.Store(path=self.dir / "mine.sqlite")
        self.s.upsert_area("a1", "Market Square", "tcn01", 8, 8)
        self.s.upsert_poi("a1", "pin", "City Gates", None, 10, 10, 0)

    def tearDown(self):
        self.s.close()
        for p in self.patches:
            p.stop()


class Store(Base):
    def test_save_list_and_search_first(self):
        self.s.save_place("a1", 40, 40, "My house")
        self.s.save_place("a1", 60, 20, "Gates stash")
        self.assertEqual([r["name"] for r in self.s.saved_places()], ["Gates stash", "My house"])
        hits = self.s.search("gate")
        self.assertEqual((hits[0]["kind"], hits[0]["name"]), ("user", "Gates stash"))   # ahead of the pin
        self.assertIn("City Gates", [h["name"] for h in hits])
        self.assertEqual(sum(h["name"] == "Gates stash" for h in hits), 1)              # not listed twice

    def test_saving_the_same_spot_renames_it(self):
        a = self.s.save_place("a1", 40, 40, "House")
        b = self.s.save_place("a1", 41, 40, "  My   house  ")
        self.assertEqual(a, b)
        self.assertEqual([r["name"] for r in self.s.saved_places()], ["My house"])

    def test_empty_name_uses_the_area_and_long_names_are_cut(self):
        self.s.save_place("a1", 5, 5, "")
        self.s.save_place("a1", 70, 70, "x" * 200)
        names = sorted(r["name"] for r in self.s.saved_places())
        self.assertEqual(names[0], "Market Square")
        self.assertEqual(len(names[1]), dbmod.MAX_PLACE_NAME)

    def test_remove_and_restore(self):
        pid = self.s.save_place("a1", 40, 40, "House")
        v = self.s.places_version()
        self.assertTrue(self.s.remove_place(pid))
        self.assertNotEqual(self.s.places_version(), v)
        self.assertEqual(self.s.saved_places(), [])
        self.assertEqual(self.s.search("house"), [])
        self.assertFalse(self.s.remove_place(pid))                    # already gone
        change = self.s.changes()[0]
        self.assertEqual(change["what"], "place_removed")
        self.assertIsNotNone(self.s.restore(change["id"]))
        self.assertEqual([r["name"] for r in self.s.saved_places()], ["House"])

    def test_only_saved_places_can_be_removed(self):
        pin = self.s.db.execute("SELECT id FROM pois WHERE kind='pin'").fetchone()[0]
        self.assertFalse(self.s.remove_place(pin))

    def test_a_saved_place_is_never_an_exit(self):
        self.s.save_place("a1", 40, 40, "Field camp")
        self.assertEqual(self.s.exit_places()["pois"]["a1"], [(10, 10)])
        self.assertIsNone(self.s.nearest_poi("a1", 40, 40, max_dist=6))

    def test_visits_never_hide_a_saved_place(self):
        self.s.save_place("a1", 10, 12, "By the gates")
        for _ in range(dbmod.RETIRE_AFTER + 1):
            self.s.end_visit("a1", [], [(10, 11)])
        self.assertEqual(len(self.s.saved_places()), 1)


class Sharing(Base):
    def rows(self, path):
        con = sqlite3.connect(path)
        try:
            return con.execute("SELECT kind, name FROM pois ORDER BY kind").fetchall()
        finally:
            con.close()

    def test_shared_export_leaves_them_out_unless_asked(self):
        self.s.save_place("a1", 40, 40, "My house")
        self.assertEqual(self.rows(self.s.export(self.dir / "share.sqlite", share=True)), [("pin", "City Gates")])
        kept = self.rows(self.s.export(self.dir / "share2.sqlite", share=True, keep_places=True))
        self.assertIn(("user", "My house"), kept)
        self.assertIn(("user", "My house"), self.rows(self.s.export(self.dir / "backup.sqlite")))

    def test_a_friends_saved_places_are_skipped(self):
        friend = dbmod.Store(path=self.dir / "friend.sqlite")
        friend.upsert_area("a1", "Market Square", "tcn01", 8, 8)
        friend.upsert_poi("a1", "pin", "Fountain", None, 30, 30, 0)
        friend.save_place("a1", 50, 50, "Their house")
        friend.close()
        added = self.s.merge(self.dir / "friend.sqlite")
        self.assertEqual((added["pois"], added["places_skipped"]), (1, 1))
        self.assertEqual(self.s.saved_places(), [])


class PickerRows(Base):
    HERE = {"area": "a1", "x": 33.0, "y": 44.0, "z": 0.0, "suggest": "City Gates"}

    def type(self, pk, text):
        for ch in text:
            pk.handle(P.EV_CHAR, ord(ch))

    def key(self, pk, code):
        return pk.handle(P.EV_KEY, code)

    def test_list_order(self):
        self.s.save_place("a1", 40, 40, "House")
        P.remember({"kind": "pin", "area": "a1", "name": "City Gates", "x": 10, "y": 10})
        pk = P.Picker(self.s)
        dest = {"kind": "spot", "area": "a1", "name": "Spot in Market", "x": 70, "y": 70}
        pk.start(True, dest=dest, here=self.HERE)
        self.assertEqual([r["kind"] for r in pk.results], ["clear", "save_dest", "save_here", "user", "pin"])

    def test_no_save_rows_without_a_spot(self):
        pk = P.Picker(self.s)
        pk.start(True, dest={"kind": "area", "area": "a1", "name": "Market Square", "x": None, "y": None})
        self.assertEqual([r["kind"] for r in pk.results], ["clear"])
        self.s.save_place("a1", 40, 40, "House")
        pk.start(True, dest={"kind": "user", "area": "a1", "name": "House", "x": 40, "y": 40, "id": 1})
        self.assertEqual([r["kind"] for r in pk.results], ["clear", "user"])     # already saved

    def test_save_here_with_the_suggested_name(self):
        pk = P.Picker(self.s)
        pk.start(False, here=self.HERE)
        self.assertIsNone(self.key(pk, P.VK_RETURN))                 # opens naming
        self.assertTrue(pk.naming and pk.open)
        action, place = self.key(pk, P.VK_RETURN)
        self.assertEqual((action, place["name"], place["x"], place["area"]), ("save", "City Gates", 33.0, "a1"))
        self.assertFalse(pk.open)

    def test_save_with_a_typed_name_and_esc_goes_back(self):
        pk = P.Picker(self.s)
        pk.start(False, here=self.HERE)
        self.key(pk, P.VK_RETURN)
        self.type(pk, "Bankk")
        self.key(pk, P.VK_BACK)
        self.assertEqual(pk.query, "Bank")
        self.assertIsNone(self.key(pk, P.VK_ESCAPE))                 # back to the list, still open
        self.assertTrue(pk.open and not pk.naming and pk.query == "")
        self.assertEqual(pk.results[0]["kind"], "save_here")
        self.key(pk, P.VK_RETURN)
        self.type(pk, "Bank")
        self.assertEqual(self.key(pk, P.VK_RETURN)[1]["name"], "Bank")

    def test_save_destination_suggests_its_name_without_the_tag(self):
        pk = P.Picker(self.s)
        pk.start(True, dest={"kind": "door", "area": "a1", "name": "The Nymph [ad_wd_17]", "x": 20, "y": 20})
        self.key(pk, P.VK_DOWN)                                      # past "Clear destination"
        self.key(pk, P.VK_RETURN)
        self.assertEqual(self.key(pk, P.VK_RETURN)[1]["name"], "The Nymph")

    def test_delete_twice_removes(self):
        self.s.save_place("a1", 40, 40, "House")
        pk = P.Picker(self.s)
        pk.start(False)
        self.assertIsNone(self.key(pk, P.VK_DELETE))
        self.assertEqual(pk.confirm, pk.results[0]["id"])
        action, row = self.key(pk, P.VK_DELETE)
        self.assertEqual((action, row["name"]), ("remove", "House"))
        self.s.remove_place(row["id"])
        pk.removed()
        self.assertEqual(pk.results, [])

    def test_any_other_key_cancels_a_first_delete(self):
        self.s.save_place("a1", 40, 40, "House")
        self.s.save_place("a1", 70, 70, "Inn")
        pk = P.Picker(self.s)
        pk.start(False)
        self.key(pk, P.VK_DELETE)
        self.key(pk, P.VK_DOWN)
        self.assertIsNone(pk.confirm)
        self.assertIsNone(self.key(pk, P.VK_DELETE))                 # asks again for the new row
        self.assertEqual(len(self.s.saved_places()), 2)

    def test_removed_places_drop_out_of_recent(self):
        pid = self.s.save_place("a1", 40, 40, "House")
        P.remember({"kind": "user", "area": "a1", "name": "House", "x": 40, "y": 40, "id": pid})
        self.s.remove_place(pid)
        pk = P.Picker(self.s)
        pk.start(False)
        self.assertEqual(pk.results, [])

    def test_page_keys_and_drawing_a_long_list(self):
        for i in range(25):
            self.s.save_place("a1", i * 3, 70, f"Place {i:02}")
        pk = P.Picker(self.s)
        pk.start(False, here=self.HERE)
        self.key(pk, P.VK_NEXT)
        self.assertEqual(pk.sel, P.PAGE)
        self.key(pk, P.VK_END)
        self.assertEqual(pk.sel, 25)
        first = panel.picker_window(len(pk.results), pk.sel)
        self.assertTrue(first <= pk.sel < first + panel.PICKER_ROWS)
        self.assertEqual(panel.render_picker(pk, self.s.area_name).size, (panel.W, panel.H))
        self.key(pk, P.VK_HOME)
        self.key(pk, P.VK_RETURN)
        self.assertEqual(panel.render_picker(pk, self.s.area_name).size, (panel.W, panel.H))   # naming


if __name__ == "__main__":
    unittest.main()
