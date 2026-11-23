"""Offline tests of the recorder's edge logic with a scripted fake session.

  python -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, recorder as R  # noqa: E402
from nwngps.session import IN_GAME, LOADING, MENU, NO_GAME, Snapshot  # noqa: E402

W = "nwnarelith.com"


EDGE = (2.0, 20.0, 0.0)      # 2 m from the west edge of a 4x4-tile area: walking off the map
MIDDLE = (20.0, 20.0, 0.0)   # nowhere near a door or an edge: a teleport


def snap(t, state=IN_GAME, server="ARE_CitiesAndPlanes", area="a1", pos=EDGE, world=W, name=None):
    if state != IN_GAME:
        return Snapshot(state, t=t)
    return Snapshot(IN_GAME, t=t, world=world, server=server, module="Arelith", area=area,
                    area_name=name or area.upper(), tileset="t", size=(4, 4), pos=pos, facing=(0, 1, 0),
                    area_ptr=0)


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.mem, self.table = None, None

    def poll(self):
        return self.script.pop(0)

    def close(self):
        pass


def run(script, **settings):
    tmp = tempfile.mkdtemp()
    conf = {**R.config.DEFAULTS, **settings}
    with mock.patch.object(dbmod, "DATA_DIR", Path(tmp)), \
         mock.patch.object(R.config, "load_settings", lambda: dict(conf)), \
         mock.patch.object(R.Recorder, "record_pois", lambda self, s: None), \
         mock.patch.object(R.maps, "read_tiles", lambda *a: None), \
         mock.patch.object(R, "log", lambda m: None):
        rec = R.Recorder()
        rec.session = FakeSession(script)
        for _ in range(len(script)):
            rec.step()
        st = rec.store(W)
        rows = [dict(r) for r in st.db.execute("SELECT * FROM transitions")]
        st.close()
        return rows


def menu(t0, seconds, state=MENU):
    return [snap(t0 + i * 0.5, state) for i in range(int(seconds * 2))]


class EdgeLogic(unittest.TestCase):
    def test_walk_between_areas(self):
        rows = run([snap(0), snap(1, LOADING), snap(2, area="a2", pos=(5, 5, 0))])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["from_area"], rows[0]["to_area"], rows[0]["kind"]), ("a1", "a2", "walk"))

    def test_brief_menu_flicker_is_still_a_walk(self):
        rows = run([snap(0), *menu(1, 1.0), snap(3, area="a2")])
        self.assertEqual([r["kind"] for r in rows], ["walk"])

    def test_relog_same_server_records_nothing(self):
        rows = run([snap(0), *menu(1, 10), snap(20, area="a2")])
        self.assertEqual(rows, [])

    def test_portal_without_menu_is_confirmed(self):
        rows = run([snap(0), snap(1, LOADING), snap(30, server="ARE_Surface", area="s1")])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["kind"], r["confirmed"], r["from_server"], r["to_server"]),
                         ("portal", 1, "ARE_CitiesAndPlanes", "ARE_Surface"))

    def test_portal_through_menu_is_unconfirmed_until_seen_again(self):
        trip = lambda t: [snap(t), *menu(t + 1, 10), snap(t + 30, server="ARE_Surface", area="s1")]
        rows = run(trip(0))
        self.assertEqual((rows[0]["kind"], rows[0]["confirmed"]), ("portal", 0))
        back = [snap(100, server="ARE_Surface", area="s1"), *menu(101, 10), snap(130)]
        rows = run(trip(0) + back + trip(200))
        portals = [r for r in rows if r["from_area"] == "a1"]
        self.assertEqual((len(portals), portals[0]["confirmed"], portals[0]["count"]), (1, 1, 2))

    def test_server_change_after_long_gap_is_relog(self):
        rows = run([snap(0), *menu(1, 10), snap(1000, server="ARE_Surface", area="s1")])
        self.assertEqual(rows, [])

    def test_game_restart_records_nothing(self):
        rows = run([snap(0), *menu(1, 5, NO_GAME), snap(20, server="ARE_Surface", area="s1")])
        self.assertEqual(rows, [])

    def test_other_world_is_separate(self):
        rows = run([snap(0), snap(1, LOADING), snap(5, world="otherpw.org", server="X", area="x1")])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()


def trip(t, frm="a1", to="a2", pos=MIDDLE, to_name=None, from_name=None):
    return [snap(t, area=frm, pos=pos, name=from_name), snap(t + 1, LOADING),
            snap(t + 2, area=to, pos=(20, 20, 0), name=to_name)]


FUGUE = dict(to="fugue1", to_name="The Fugue Plane")


class EdgeCases(unittest.TestCase):
    def test_teleport_from_mid_area_is_a_jump_and_not_trusted(self):
        rows = run(trip(0))
        self.assertEqual((rows[0]["kind"], rows[0]["confirmed"]), ("jump", 0))

    def test_jump_from_the_same_spot_is_trusted_after_three(self):
        rows = [r for r in run(trip(0) + trip(10) + trip(20)) if r["from_area"] == "a1"]
        self.assertEqual((len(rows), rows[0]["count"], rows[0]["confirmed"]), (1, 3, 1))
        rows = run(trip(0) + trip(10))
        self.assertEqual(rows[0]["confirmed"], 0)

    def test_jumps_from_different_spots_stay_untrusted(self):
        rows = run(trip(0) + trip(10, pos=(30, 30, 0)) + trip(20, pos=(15, 25, 0)))
        self.assertTrue(rows and all(r["kind"] == "jump" and r["confirmed"] == 0 for r in rows))

    def test_death_into_fugue_is_never_routed(self):
        rows = [r for r in run(trip(0, **FUGUE) + trip(10, **FUGUE) + trip(20, **FUGUE)) if r["from_area"] == "a1"]
        self.assertEqual((len(rows), rows[0]["kind"], rows[0]["confirmed"]), (1, "death", 0))

    def test_death_at_the_map_edge_is_still_death(self):
        rows = run(trip(0, pos=EDGE, **FUGUE))
        self.assertEqual(rows[0]["kind"], "death")

    def test_leaving_the_fugue_is_a_respawn(self):
        rows = run(trip(0, frm="fugue1", from_name="The Fugue Plane", to="temple"))
        self.assertEqual((rows[0]["kind"], rows[0]["confirmed"]), ("respawn", 1))

    def test_death_areas_setting_is_used(self):
        rows = run(trip(0, to="gy", to_name="Graveyard"), death_areas=["graveyard"])
        self.assertEqual(rows[0]["kind"], "death")

    def test_cross_server_teleport_is_a_jump_not_a_portal(self):
        rows = run([snap(0, pos=MIDDLE), snap(1, LOADING), snap(30, server="ARE_Surface", area="s1")])
        self.assertEqual((rows[0]["kind"], rows[0]["confirmed"]), ("jump", 0))

    def test_dm_mode_records_no_links(self):
        rows = run([snap(0), snap(1, LOADING), snap(2, area="a2")] + trip(10), dm_mode=True)
        self.assertEqual(rows, [])


def temp_store():
    tmp = tempfile.mkdtemp()
    patch = mock.patch.object(dbmod, "DATA_DIR", Path(tmp))
    patch.start()
    st = dbmod.Store(W)
    return st, patch


class Promotion(unittest.TestCase):
    def setUp(self):
        self.st, self.patch = temp_store()

    def tearDown(self):
        self.st.close()
        self.patch.stop()

    def test_jump_becomes_walk_when_a_door_turns_up(self):
        st = self.st
        tid, _ = st.add_transition("a1", (20, 20, 0), "a2", (5, 5, 0), "S", "S", kind="jump", confirmed=False)
        self.assertEqual(st.promote_jumps("a1"), [])
        st.upsert_poi("a1", "door", "Door", None, 21.0, 20.5, 0.0)
        self.assertEqual(st.promote_jumps("a1"), [tid])
        r = st.db.execute("SELECT kind, confirmed FROM transitions WHERE id=?", (tid,)).fetchone()
        self.assertEqual(tuple(r), ("walk", 1))

    def test_seen_again_as_walk_upgrades_a_jump(self):
        st = self.st
        st.add_transition("a1", (20, 20, 0), "a2", (5, 5, 0), kind="jump", confirmed=False)
        st.add_transition("a1", (20.5, 20, 0), "a2", (5, 5, 0), kind="walk", confirmed=True)
        r = st.db.execute("SELECT kind, confirmed, count FROM transitions").fetchone()
        self.assertEqual(tuple(r), ("walk", 1, 2))

    def test_death_is_never_confirmed_even_by_hand_merges(self):
        st = self.st
        st.add_transition("a1", (20, 20, 0), "fugue", (5, 5, 0), kind="death", confirmed=False)
        st.add_transition("a1", (20, 20, 0), "fugue", (5, 5, 0), kind="death", confirmed=True)
        self.assertEqual(st.db.execute("SELECT confirmed FROM transitions").fetchone()[0], 0)

    def test_forget_and_trust_links(self):
        st = self.st
        tid, _ = st.add_transition("a1", (20, 20, 0), "a2", (5, 5, 0), kind="jump", confirmed=False)
        self.assertTrue(st.set_link(tid, confirmed=True))
        self.assertEqual(st.db.execute("SELECT confirmed FROM transitions").fetchone()[0], 1)
        self.assertFalse(st.set_link(999, confirmed=True))
        self.assertTrue(Path(st.forget_link(tid)).exists())      # backed up first
        self.assertEqual(st.db.execute("SELECT COUNT(*) FROM transitions").fetchone()[0], 0)
        self.assertIsNone(st.forget_link(tid))
