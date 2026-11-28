"""Walking paths inside an area: tile walkmeshes are read safely and laid out like the tile art, the
path goes around walls instead of through them, ends as near an exit as can be reached, and the
directions use it (walking distance, head for the next turn) - or fall back to a straight line."""
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import nav as N, walkmesh as W  # noqa: E402

SURFACEMAT = b"2DA V2.0\n\n   Label Walk WalkCheck\n0  NotDefined 0 0\n1  Dirt 1 1\n7  Nonwalk 0 0\n"


def wok(rects, extra=""):
    """An ASCII walkmesh of axis-aligned rectangles (x0, y0, x1, y1, material), tile-local metres."""
    verts, faces = [], []
    for x0, y0, x1, y1, mat in rects:
        k = len(verts)
        verts += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        faces += [(k, k + 1, k + 2, mat), (k, k + 2, k + 3, mat)]
    text = "#MAXWALKMESH ASCII\nbeginwalkmeshgeom t\nnode aabb m\n" + extra
    text += f"  verts {len(verts)}\n" + "".join(f"    {x} {y} 0.0\n" for x, y in verts)
    text += f"  faces {len(faces)}\n" + "".join(f"    {a} {b} {c} 1 0 0 0 {m}\n" for a, b, c, m in faces)
    return (text + "endnode\nendwalkmeshgeom t\n").encode()


FLOOR = wok([(-5, -5, 5, 5, 1)])
EAST_HALF = wok([(0, -5, 5, 5, 1), (-5, -5, 0, 5, 7)])
WALL = wok([(-5, -5, 5, 5, 1), (-0.5, -5, 0.5, 3, 7)])      # a wall across the tile, a gap at the north end
SET = (b"[GENERAL]\nInterior=0\n[TILE0]\nModel=t_floor\n[TILE1]\nModel=t_wall\n[TILE2]\nModel=t_east\n"
       b"[TILE3]\nModel=t_none\n[END]\n")


class FakeRes:
    def __init__(self, over=None):
        self.files = {("surfacemat", W.SURFACEMAT): SURFACEMAT, ("tst01", "set"): SET,
                      ("t_floor", W.WOK): FLOOR, ("t_wall", W.WOK): WALL, ("t_east", W.WOK): EAST_HALF}
        self.files.update(over or {})

    def get(self, name, ext):
        return self.files.get((name, ext))


class Cached(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(W, "MAP_DIR", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()


class Parsing(unittest.TestCase):
    def test_walkable_materials_come_from_the_table(self):
        self.assertEqual(W.walk_materials(SURFACEMAT), {1})
        self.assertIsNone(W.walk_materials(b"not a table"))
        self.assertIsNone(W.walk_materials(b"2DA V2.0\n\n Label Foo\n0 x 1\n"))
        self.assertIsNone(W.walk_materials(b"2DA V2.0\n" + b"x" * (W.MAX_2DA_BYTES + 1)))

    def test_triangles_and_their_materials(self):
        tris = W.parse_wok(EAST_HALF)
        self.assertEqual(len(tris), 4)
        self.assertEqual(sorted({t[6] for t in tris}), [1, 7])

    def test_the_node_offset_and_turn_are_applied(self):
        tris = W.parse_wok(wok([(1, 0, 2, 1, 1)], extra="  position 1.0 0.0 2.0\n  orientation 0 0 1 1.5707963\n"))
        xs = [v for t in tris for v in t[0:6:2]]
        ys = [v for t in tris for v in t[1:6:2]]
        # (1..2, 0..1) turned a quarter left is (-1..0, 1..2); then moved 1 m east: (0..1, 1..2)
        self.assertAlmostEqual(min(xs), 0.0, places=5)
        self.assertAlmostEqual(max(xs), 1.0, places=5)
        self.assertAlmostEqual(min(ys), 1.0, places=5)
        self.assertAlmostEqual(max(ys), 2.0, places=5)

    def test_bad_walkmeshes_are_refused(self):
        with self.assertRaises(ValueError):
            W.parse_wok(b"verts 99999999\n")
        with self.assertRaises(ValueError):
            W.parse_wok(b"verts 1\n0 0 0\nfaces 1\n0 1 2 1 0 0 0 1\n")       # points past its vertices
        with self.assertRaises(ValueError):
            W.parse_wok(b"x" * (W.MAX_WOK_BYTES + 1))
        with self.assertRaises(ValueError):
            W.parse_wok(b"faces 1\n0 0 0 1 0 0 0 1\n")
        far = W.parse_wok(wok([(100, 100, 101, 101, 1), (-1, -1, 1, 1, 1)]))
        self.assertEqual(len(far), 2)                                        # far outside a tile: dropped
        nan = W.parse_wok(wok([(-1, -1, 1, 1, 1)]).replace(b"-1 -1 0.0", b"nan -1 0.0"))
        self.assertTrue(all(all(math.isfinite(v) for v in t[:6]) for t in nan))


class Grid(Cached):
    def test_tiles_turn_like_the_tile_art(self):
        g = W.Grids(FakeRes())
        n = W.TILE_CELLS
        east = g.grid("tst01", 1, 1, [(2, 0, 0)])
        self.assertTrue(east[:, n // 2:].all() and not east[:, :n // 2].any())
        north = g.grid("tst01", 1, 1, [(2, 1, 0)])                   # a quarter turn left: east -> north
        self.assertTrue(north[n // 2:, :].all() and not north[:n // 2, :].any())
        west = g.grid("tst01", 1, 1, [(2, 2, 0)])
        self.assertTrue(west[:, :n // 2].all() and not west[:, n // 2:].any())

    def test_tiles_sit_at_their_place_in_the_area(self):
        grid = W.Grids(FakeRes()).grid("tst01", 2, 2, [(2, 0, 0), (0, 0, 0), (0, 0, 0), (2, 2, 0)])
        self.assertEqual(grid.shape, (2 * W.TILE_CELLS, 2 * W.TILE_CELLS))
        self.assertFalse(grid[W.cell_of(2, 5)[::-1]])         # SW tile: only its east half
        self.assertTrue(grid[W.cell_of(8, 5)[::-1]])
        self.assertTrue(grid[W.cell_of(12, 18)[::-1]])        # NE tile: only its west half
        self.assertFalse(grid[W.cell_of(18, 18)[::-1]])

    def test_cached_on_disk_and_read_back(self):
        g = W.Grids(FakeRes())
        tiles = [(1, 0, 0), (0, 3, 0)]
        first = g.grid("tst01", 2, 1, tiles)
        self.assertEqual(len(list(self.dir.glob("*.walk*"))), 1)
        again = W.Grids(FakeRes({("t_wall", W.WOK): None})).grid("tst01", 2, 1, tiles)   # from the file
        self.assertTrue((first == again).all())
        path = W.Grids.path("tst01", 2, 1, tiles)
        path.write_bytes(path.read_bytes()[:10])                     # damaged: built again
        self.assertTrue((g.grid("tst01", 2, 1, tiles) == first).all())

    def test_no_table_or_mostly_missing_walkmeshes_means_no_grid(self):
        self.assertIsNone(W.Grids(FakeRes({("surfacemat", W.SURFACEMAT): None})).grid("tst01", 1, 1, [(0, 0, 0)]))
        self.assertIsNone(W.Grids(FakeRes()).grid("tst01", 3, 1, [(3, 0, 0), (3, 0, 0), (0, 0, 0)]))
        self.assertIsNone(W.Grids(FakeRes({("t_floor", W.WOK): b"garbage"})).grid("tst01", 1, 1, [(0, 0, 0)]))
        self.assertIsNone(W.Grids(FakeRes()).grid("tst01", 99, 1, [(0, 0, 0)] * 99))


class Search(Cached):
    def grid(self):
        return W.Grids(FakeRes()).grid("tst01", 3, 1, [(0, 0, 0), (1, 0, 0), (0, 0, 0)])

    def test_the_path_goes_around_the_wall(self):
        grid = self.grid()
        path = W.find_path(grid, (12.0, 2.0), (18.0, 2.0))       # either side of the wall at x = 15
        self.assertEqual((path[0], path[-1]), ((12.0, 2.0), (18.0, 2.0)))
        self.assertTrue(any(y > 8 for _x, y in path[1:-1]))       # through the gap at the north end
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        self.assertGreater(length, 14)
        self.assertLess(length, 18)                               # and no longer than it has to be
        for a, b in zip(path[1:], path[2:-1]):                    # each straightened leg is walkable
            self.assertTrue(W.line_clear(grid, W.cell_of(*a), W.cell_of(*b)))

    def test_open_ground_is_one_straight_leg(self):
        self.assertEqual(W.find_path(self.grid(), (2.0, 2.0), (8.0, 8.0)), [(2.0, 2.0), (8.0, 8.0)])

    def test_an_exit_past_the_walkable_edge_is_still_reached(self):
        grid = W.Grids(FakeRes()).grid("tst01", 2, 1, [(0, 0, 0), (2, 2, 0)])   # x 15..20 is solid
        path = W.find_path(grid, (2.0, 5.0), (19.0, 5.0))
        self.assertIsNotNone(path)
        self.assertLess(abs(path[-2][0] - 15), 1.5 if len(path) > 2 else 99)
        self.assertIsNone(W.find_path(grid, (2.0, 5.0), (19.0 + W.SNAP_GOAL, 5.0)))   # too far from any floor

    def test_walled_off_gets_as_close_as_it_can(self):
        grid = self.grid()
        grid[:, int(15 / W.CELL)] = False                         # close the gap: no way through
        path = W.find_path(grid, (12.0, 2.0), (18.0, 2.0))
        self.assertTrue(path is None or all(x < 15 for x, _y in path[:-1]))
        grid[:, :int(15 / W.CELL)] = False                        # and nowhere to stand on your side
        self.assertIsNone(W.find_path(grid, (12.0, 2.0), (18.0, 2.0)))


class Following(unittest.TestCase):
    PATH = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

    def test_rest_of_the_path_from_where_you_are(self):
        r = W.Route("a", (10.0, 10.0), list(self.PATH))
        w = r.follow((4.0, 0.5))
        self.assertEqual(w.points[0], (4.0, 0.5))
        self.assertAlmostEqual(w.length, math.dist((4, 0.5), (10, 0)) + 10, places=6)
        self.assertEqual(w.aim, (10.0, 0.0))
        self.assertAlmostEqual(w.off, 0.5)
        w = r.follow((9.5, 0.2))                                  # at the corner: head for the next leg
        self.assertEqual(w.aim, (10.0, 10.0))
        w = r.follow((10.0, 5.0))
        self.assertEqual(w.points, [(10.0, 5.0), (10.0, 10.0)])
        self.assertEqual(r.follow((5.0, 0.0)).points[1:], [(10.0, 10.0)])   # never goes back a leg


def snap_at(x, y, facing=(0.0, 1.0, 0.0), area="a1"):
    return SimpleNamespace(state="IN_GAME", area=area, pos=(x, y, 0.0), facing=facing)


class Directions(Cached):
    def setUp(self):
        super().setUp()
        self.paths = W.Paths(log=lambda m: None, make_resources=lambda host: FakeRes())

    def wait(self, area, pos, target, ok=lambda w: True):
        for _ in range(200):
            w = self.paths.walk(area, pos, target)
            if w and ok(w):
                return w
            time.sleep(0.01)
        return None

    def test_found_in_the_background_then_followed(self):
        self.paths.set_area("a1", ("tst01", 3, 1, [(0, 0, 0), (1, 0, 0), (0, 0, 0)]))
        w = self.wait("a1", (12.0, 2.0), (18.0, 2.0))
        self.assertIsNotNone(w)
        self.assertGreater(w.length, 14)
        self.assertGreater(w.aim[1], 8)                           # head north, for the gap
        self.assertIsNone(self.paths.walk("a2", (12.0, 2.0), (18.0, 2.0)))  # another area: straight line
        self.paths.set_area("a2", None)                           # an area without a layout
        self.assertIsNone(self.paths.walk("a2", (12.0, 2.0), (18.0, 2.0)))

    def test_straying_far_searches_again_from_where_you_are(self):
        self.paths.set_area("a1", ("tst01", 3, 1, [(0, 0, 0), (0, 0, 0), (0, 0, 0)]))
        first = self.wait("a1", (2.0, 2.0), (28.0, 2.0))
        self.assertEqual(len(first.points), 2)
        self.assertIsNone(self.paths.walk("a1", (14.0, 2.0 + W.LOST + 1), (28.0, 2.0)))   # lost: straight
        again = self.wait("a1", (2.0, 9.0), (28.0, 2.0), ok=lambda w: w.off < 0.01)   # 7 m off: a new path
        self.assertIsNotNone(again)
        self.assertEqual(again.points, [(2.0, 9.0), (28.0, 2.0)])

    def test_navigator_uses_the_walking_path(self):
        self.paths.set_area("a1", ("tst01", 3, 1, [(0, 0, 0), (1, 0, 0), (0, 0, 0)]))
        store = mock.MagicMock()
        nav = N.Navigator(store, {"kind": "place", "area": "a1", "name": "Spot", "x": 18.0, "y": 2.0}, self.paths)
        with mock.patch.object(N.R, "plan", return_value=[]):
            g = nav.update(snap_at(12.0, 2.0))
            self.assertEqual(g.status, "NAV")
            self.assertAlmostEqual(g.distance, 6.0)              # nothing found yet: straight line
            self.assertIsNone(g.path)
            self.wait("a1", (12.0, 2.0), (18.0, 2.0))
            g = nav.update(snap_at(12.0, 2.0))
        self.assertGreater(g.distance, 14)                        # walking distance around the wall
        self.assertEqual(g.path[0], (12.0, 2.0))
        self.assertLess(abs(g.bearing), 30)                       # heading north for the gap, not east
        self.assertLess(abs(g.relative), 30)

    def test_without_numpy_it_is_straight_lines(self):
        with mock.patch.object(W, "np", None):
            self.paths.set_area("a1", ("tst01", 1, 1, [(0, 0, 0)]))
            self.assertIsNone(self.paths.walk("a1", (1.0, 1.0), (8.0, 8.0)))


if __name__ == "__main__":
    unittest.main()
