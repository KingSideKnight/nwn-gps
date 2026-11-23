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


if __name__ == "__main__":
    unittest.main()
