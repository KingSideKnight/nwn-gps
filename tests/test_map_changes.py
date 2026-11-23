"""The server changes a map: layouts, removed / moved pins and doors, re-pointed exits."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, recorder as R  # noqa: E402
from nwngps.session import IN_GAME, LOADING, Snapshot  # noqa: E402

W = "nwnarelith.com"
NEAR = [(21.0, 20.0)]          # a scan position next to the door at (20, 20)
FAR = [(200.0, 200.0)]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp()))
        self.patch.start()
        self.st = dbmod.Store(W)
        self.st.upsert_area("a1", "A1", "t", 4, 4)
        self.st.upsert_area("a2", "A2", "t", 4, 4)
        self.st.upsert_area("a3", "A3", "t", 4, 4)

    def tearDown(self):
        self.st.close()
        self.patch.stop()

    def door(self, x=20.0, y=20.0, name="Shop"):
        return self.st.upsert_poi("a1", "door", name, None, x, y, 0.0)

    def visits(self, n, seen, path=NEAR):
        return [self.st.end_visit("a1", seen, path, size=(4, 4)) for _ in range(n)]

    def retired(self, pid):
        return self.st.poi(pid)["retired"] is not None


class PoisGoing(StoreCase):
    def test_missing_three_visits_in_a_row_is_hidden(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(2, [other])
        self.assertFalse(self.retired(gone))
        self.visits(1, [other])
        self.assertTrue(self.retired(gone))
        self.assertEqual([p["name"] for p in self.st.area_pois("a1")], ["Inn"])
        self.assertEqual(self.st.search("Shop"), [])
        self.assertIsNone(self.st.nearest_poi("a1", 20, 20, max_dist=3))

    def test_being_seen_resets_the_count(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(2, [other])
        self.visits(1, [gone, other])
        self.visits(2, [other])
        self.assertFalse(self.retired(gone))

    def test_far_away_visits_dont_count(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(5, [other], path=FAR)
        self.assertFalse(self.retired(gone))

    def test_visits_that_saw_too_little_dont_count(self):
        ids = [self.door(20 + i, 20, f"D{i}") for i in range(4)]
        self.assertEqual(self.visits(5, ids[:1]), [None] * 5)      # 1 of 4 nearby: still loading
        self.assertFalse(any(self.retired(i) for i in ids))

    def test_doors_not_read_arent_missed(self):
        gone = self.door()
        pin = self.st.upsert_poi("a1", "pin", "Market", None, 22, 20, 0)
        for _ in range(5):
            self.st.end_visit("a1", [pin], NEAR, kinds=("pin",), size=(4, 4))
        self.assertFalse(self.retired(gone))

    def test_coming_back_unhides_and_logs(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(3, [other])
        self.assertEqual(self.door(), gone)
        self.assertFalse(self.retired(gone))
        self.assertEqual([c["what"] for c in self.st.changes()][:2], ["poi_back", "poi_retired"])

    def test_restore(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(3, [other])
        cid = self.st.changes()[0]["id"]
        self.assertIn("Shop", self.st.restore(cid))
        self.assertFalse(self.retired(gone))
        self.assertIsNone(self.st.restore(cid))             # only once
        self.assertTrue(list((dbmod.DATA_DIR / "backups").glob("*before-restore*")))

    def test_panel_notices_retirement(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        v = self.st.pois_version("a1")
        self.visits(3, [other])
        self.assertNotEqual(self.st.pois_version("a1"), v)

    def test_merge_cant_bring_back_a_retired_door(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(3, [other])
        friend = dbmod.Store(path=dbmod.DATA_DIR / "friend.sqlite")
        friend.upsert_poi("a1", "door", "Shop", None, 20.0, 20.0, 0.0)
        friend.close()
        self.st.merge(dbmod.DATA_DIR / "friend.sqlite")
        self.assertTrue(self.retired(gone))


class LinksGoing(StoreCase):
    def link(self, frm=(20.0, 21.0, 0.0), to="a2", **kw):
        return self.st.add_transition("a1", frm, to, (5.0, 5.0, 0.0), "S", "S", **kw)[0]

    def stale(self, tid):
        return self.st.db.execute("SELECT stale FROM transitions WHERE id=?", (tid,)).fetchone()[0] is not None

    def test_link_from_a_removed_door_goes_stale(self):
        gone, other = self.door(), self.door(32, 20, "Inn")
        tid = self.link()
        self.visits(3, [other])
        self.assertTrue(self.stale(tid))
        self.assertEqual(self.st.transitions(), [])
        v = self.st.links_version()
        self.link()                                    # walked again: trusted again
        self.assertFalse(self.stale(tid))
        self.assertNotEqual(self.st.links_version(), v)

    def test_map_edge_link_survives_a_removed_door(self):
        gone, other = self.door(3, 20), self.door(32, 20, "Inn")
        tid = self.link(frm=(2.0, 20.0, 0.0))
        self.visits(3, [other], path=[(3.0, 20.0)])
        self.assertFalse(self.stale(tid))

    def test_door_pointing_somewhere_new_supersedes_the_old_link(self):
        self.door()
        old = self.link(to="a2")
        new = self.link(frm=(20.3, 21.0, 0.0), to="a3")
        self.assertTrue(self.stale(old))
        self.assertFalse(self.stale(new))
        self.link(to="a2")                             # and back again
        self.assertFalse(self.stale(old))
        self.assertTrue(self.stale(new))

    def test_neighbouring_doors_dont_supersede_each_other(self):
        self.door(), self.door(24, 20, "Inn")
        a, b = self.link(to="a2"), self.link(frm=(24.0, 21.0, 0.0), to="a3")
        self.assertFalse(self.stale(a) or self.stale(b))

    def test_arrival_point_follows_the_latest_walk(self):
        tid = self.link()
        self.st.add_transition("a1", (20.0, 21.0, 0.0), "a2", (9.0, 9.0, 0.0), "S", "S")
        r = self.st.db.execute("SELECT to_x, to_y FROM transitions WHERE id=?", (tid,)).fetchone()
        self.assertEqual(tuple(r), (9.0, 9.0))

    def test_imported_link_from_a_door_that_leads_elsewhere_is_stale(self):
        self.door()
        mine = self.link(to="a2")
        friend = dbmod.Store(path=dbmod.DATA_DIR / "friend.sqlite")
        friend.add_transition("a1", (20.2, 21.0, 0.0), "a3", (5.0, 5.0, 0.0), "S", "S")
        friend.close()
        self.st.merge(dbmod.DATA_DIR / "friend.sqlite")
        theirs = self.st.db.execute("SELECT id FROM transitions WHERE to_area='a3'").fetchone()[0]
        self.assertTrue(self.stale(theirs))
        self.assertFalse(self.stale(mine))

    def test_merge_skips_their_stale_links_and_keeps_mine_stale(self):
        self.door()
        old = self.link(to="a2")
        self.link(frm=(20.3, 21.0, 0.0), to="a3")      # mine went stale
        friend = dbmod.Store(path=dbmod.DATA_DIR / "friend.sqlite")
        friend.add_transition("a1", (20.0, 21.0, 0.0), "a2", (5.0, 5.0, 0.0), "S", "S")
        friend.close()
        added = self.st.merge(dbmod.DATA_DIR / "friend.sqlite")
        self.assertTrue(self.stale(old))
        self.assertEqual(added["transitions"], 0)

    def test_share_export_drops_the_change_log(self):
        gone, other = self.door(), self.door(25, 20, "Inn")
        self.visits(3, [other])
        out = self.st.export(dbmod.DATA_DIR / "share.sqlite", share=True)
        s = dbmod.Store(path=out)
        self.assertEqual(s.changes(), [])
        s.close()


class Layouts(StoreCase):
    T1 = [[1, 0, 0]] * 16
    T2 = [[2, 1, 0]] * 16

    def test_new_same_changed_restore(self):
        st = self.st
        self.assertEqual(st.check_layout("a1", "t", 4, 4, self.T1), "new")
        self.assertIsNone(st.check_layout("a1", "t", 4, 4, [tuple(t) for t in self.T1]))
        self.assertEqual(st.check_layout("a1", "t", 4, 4, self.T2), "changed")
        self.assertEqual(st.tiles("a1")[3][0], (2, 1, 0))
        self.assertTrue(list((dbmod.DATA_DIR / "backups").glob("*before-layout*")))
        st.restore(st.changes()[0]["id"])
        self.assertEqual(st.tiles("a1")[3][0], (1, 0, 0))


def snap(t, area="a1", pos=(20.0, 20.0, 0.0), state=IN_GAME):
    if state != IN_GAME:
        return Snapshot(state, t=t)
    return Snapshot(IN_GAME, t=t, world=W, server="S", module="Arelith", area=area, area_name=area.upper(),
                    tileset="t", size=(4, 4), pos=pos, facing=(0, 1, 0), area_ptr=0)


class FakeSession:
    def __init__(self, script):
        self.script, self.mem, self.table = list(script), None, object()

    def poll(self):
        return self.script.pop(0)

    def close(self):
        pass


class RecorderIntegration(unittest.TestCase):
    """Real record_pois / end_visit, with scripted doors and tile reads."""

    def run_script(self, script, doors, tiles):
        """doors / tiles: callables of the snapshot time."""
        self.tmp = Path(tempfile.mkdtemp())
        now = {"t": 0}
        with mock.patch.object(dbmod, "DATA_DIR", self.tmp), \
             mock.patch.object(R.objects, "map_pins", lambda *a: []), \
             mock.patch.object(R.objects, "doors", lambda *a: doors(now["t"])), \
             mock.patch.object(R.maps, "read_tiles", lambda *a: tiles(now["t"])), \
             mock.patch.object(R, "log", lambda m: None):
            rec = R.Recorder()
            rec.session = FakeSession(script)
            for s in script:
                now["t"] = s.t
                rec.step()
            st = rec.store(W)
            out = ([dict(r) for r in st.db.execute("SELECT name, retired FROM pois ORDER BY id")],
                   st.tiles("a1"), [c["what"] for c in st.changes()])
            st.close()
        return out

    @staticmethod
    def visit(t0, area="a1"):
        # arrive, stay ~25 s (two scans 10 s apart after settling), leave
        return [snap(t0 + i, area) for i in range(0, 26, 2)] + [snap(t0 + 27, state=LOADING)]

    def test_door_removed_by_the_server(self):
        shop = {"kind": "door", "name": "Shop", "tag": None, "pos": (20.0, 21.0, 0.0)}
        inn = {"kind": "door", "name": "Inn", "tag": None, "pos": (24.0, 21.0, 0.0)}
        script = self.visit(0) + self.visit(100, "a2")
        for k in range(1, 5):
            script += self.visit(200 * k) + self.visit(200 * k + 100, "a2")
        pois, _, whats = self.run_script(script, lambda t: [shop, inn] if t < 200 else [inn],
                                         lambda t: [[1, 0, 0]] * 16)
        by = {p["name"]: p["retired"] for p in pois}
        self.assertIsNotNone(by["Shop"])
        self.assertIsNone(by["Inn"])
        self.assertIn("poi_retired", whats)

    def test_layout_change_needs_two_matching_reads(self):
        t1, t2 = [[1, 0, 0]] * 16, [[2, 0, 0]] * 16
        # one odd read in visit 2, then a real change in visit 3
        script = self.visit(0) + self.visit(100, "a2") + self.visit(200) + self.visit(300, "a2") + self.visit(400)
        tiles = lambda t: t2 if (200 <= t < 210 or t >= 400) else t1
        _, rec, whats = self.run_script(script, lambda t: [], tiles)
        self.assertEqual(whats.count("layout"), 1)
        self.assertEqual(rec[3][0], (2, 0, 0))


if __name__ == "__main__":
    unittest.main()
