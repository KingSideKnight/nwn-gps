import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import ingame  # noqa: E402


class FakeShm:
    def __init__(self):
        self.times = []

    def publish(self, img):
        self.times.append(time.time())


class Heartbeat(unittest.TestCase):
    def test_panel_kept_alive_while_the_loop_is_busy(self):
        g = ingame.InGame.__new__(ingame.InGame)       # no game, store or DLL needed
        g.shm, g.pub_lock, g.stopping = FakeShm(), threading.Lock(), False
        g.publish("frame")
        g.last_img = "frame"
        threading.Thread(target=g.heartbeat, daemon=True).start()
        time.sleep(2.6)                                 # main loop stuck (e.g. the login scan)
        with g.pub_lock:
            g.stopping = True
        gaps = [b - a for a, b in zip(g.shm.times, g.shm.times[1:])]
        self.assertGreaterEqual(len(g.shm.times), 2)
        self.assertLess(max(gaps + [time.time() - g.shm.times[-1]]), 2.0)   # the DLL gives up at 3 s

    def test_nothing_published_after_stopping(self):
        g = ingame.InGame.__new__(ingame.InGame)
        g.shm, g.pub_lock, g.stopping = FakeShm(), threading.Lock(), True
        g.publish("frame")
        self.assertEqual(g.shm.times, [])



class PoisRefresh(unittest.TestCase):
    def test_pins_saved_after_arrival_show_up(self):
        import tempfile
        from unittest import mock
        from nwngps import db as dbmod
        with mock.patch.object(dbmod, "DATA_DIR", Path(tempfile.mkdtemp())):
            st = dbmod.Store("w")
            g = ingame.InGame.__new__(ingame.InGame)
            g.store = st
            g.load_pois("farm")                       # we arrive first: nothing saved yet
            self.assertEqual(g.pois, [])
            st.upsert_poi("farm", "pin", "Mill", None, 10, 10, 0)    # recorder, a second later
            st.upsert_poi("farm", "door", "Door", None, 20, 20, 0)
            st.commit()
            g.load_pois("farm")
            self.assertEqual(sorted(p["name"] for p in g.pois), ["Door", "Mill"])
            st.close()


if __name__ == "__main__":
    unittest.main()
