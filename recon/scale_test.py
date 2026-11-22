"""Time the GPS on a synthetic world the size of Arelith (or bigger). Uses a temporary database.

  python scale_test.py [areas=3000]
A grid of exterior areas joined edge-to-edge, an interior behind a door in every 3rd area,
50 POIs per area, tile layouts for all.
"""
import random
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, route, worldmap  # noqa: E402
from nwngps.fullmap import FullMap  # noqa: E402
from nwngps.nav import Navigator  # noqa: E402
from nwngps.session import Snapshot  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
side = int(N ** 0.5)
tmp = Path(tempfile.mkdtemp())
mock.patch.object(dbmod, "DATA_DIR", tmp).start()
s = dbmod.Store(path=tmp / "big.sqlite")
rnd = random.Random(1)


class FakeMaps:            # tilesets: "ext" exterior, "int" interior; solid-colour art
    def is_interior(self, name):
        return name == "int"

    def image(self, tileset, w, h, tiles):
        from PIL import Image
        return Image.new("RGBA", (w * 32, h * 32), (60, 90, 60, 255))


def timed(label, f):
    t = time.perf_counter()
    r = f()
    print(f"{label:42} {1000 * (time.perf_counter() - t):9.1f} ms")
    return r


def populate():
    for i in range(side):
        for j in range(side):
            a = f"x{i}_{j}"
            s.upsert_area(a, f"Area {i},{j}", "ext", 16, 16)
            s.save_tiles(a, "ext", 16, 16, [[1, 0, 0]] * 256)
            for k in range(50):
                s.upsert_poi(a, "pin" if k < 5 else "door", f"Place {i}-{j}-{k}", None,
                             rnd.uniform(5, 155), rnd.uniform(5, 155), 0)
            if i + 1 < side:
                s.add_transition(a, (159, 80, 0), f"x{i + 1}_{j}", (1, 80, 0))
                s.add_transition(f"x{i + 1}_{j}", (1, 80, 0), a, (159, 80, 0))
            if j + 1 < side:
                s.add_transition(a, (80, 159, 0), f"x{i}_{j + 1}", (80, 1, 0))
            if (i + j) % 3 == 0:
                s.upsert_area(f"in{i}_{j}", f"House {i},{j}", "int", 4, 4)
                s.add_transition(a, (40, 40, 0), f"in{i}_{j}", (20, 2, 0))
    s.commit()


timed(f"populate {side * side} areas", populate)
print("stats:", s.stats(), f"db {(tmp / 'big.sqlite').stat().st_size / 1e6:.1f} MB")
trans = timed("load transitions", lambda: s.transitions())
timed("reverse edges", lambda: route.with_reverse_edges(trans))
steps = timed("route corner to corner", lambda: route.plan(trans, "x0_0", (5, 5), f"x{side - 1}_{side - 1}", (80, 80)))
print("   steps:", len(steps))
timed("search 'Place 7-'", lambda: s.search("Place 7-"))
dest = dict(s.search(f"Place {side - 1}-{side - 1}-3")[0])
nav = Navigator(s, dest)
snap = Snapshot("IN_GAME", area="x3_3", area_name="Area 3,3", pos=(80.0, 80.0, 0.0), facing=(0, 1, 0),
                size=(16, 16), server="S")
timed("navigator update (replan)", lambda: nav.update(snap))
w = timed("build world map", lambda: worldmap.build(s, FakeMaps()))
print("   clusters:", len(set(w.cluster.values())), "placed:", len(w.origin), "interiors:", len(w.interiors))
fm = FullMap(s, FakeMaps())
fm.world = w
g = nav.update(snap)
timed("full map frame (1600x900)", lambda: fm.render((1600, 900), snap, g, nav, None))
timed("full map frame again", lambda: fm.render((1600, 900), snap, g, nav, None))
nav.plan_t = 0
timed("navigator replan, graph cached", lambda: nav.update(snap))
s.close()
