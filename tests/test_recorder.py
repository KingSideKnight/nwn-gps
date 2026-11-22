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


def snap(t, state=IN_GAME, server="ARE_CitiesAndPlanes", area="a1", pos=(10.0, 10.0, 0.0), world=W):
    if state != IN_GAME:
        return Snapshot(state, t=t)
    return Snapshot(IN_GAME, t=t, world=world, server=server, module="Arelith", area=area,
                    area_name=area.upper(), tileset="t", size=(4, 4), pos=pos, facing=(0, 1, 0), area_ptr=0)


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.mem, self.table = None, None

    def poll(self):
        return self.script.pop(0)

    def close(self):
        pass


def run(script):
    tmp = tempfile.mkdtemp()
    with mock.patch.object(dbmod, "DATA_DIR", Path(tmp)), \
         mock.patch.object(R.Recorder, "record_pois", lambda self, s: None), \
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
