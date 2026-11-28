"""The area-map cache is shared by the in-game overlay and the map window: a damaged cached file is
drawn again instead of leaving the area without a map, and saving never leaves temporary files."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps as M  # noqa: E402

SET = b"[GENERAL]\nInterior=1\n[TILE0]\nImageMap2D=mi_test01\n[TILE1]\nImageMap2D=mi_test02\n[END]\n"


def tga(color):
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), color).save(buf, format="TGA")
    return buf.getvalue()


class FakeRes:
    files = {("tds01", "set"): SET, ("mi_test01", "tga"): tga((200, 0, 0, 255)),
             ("mi_test02", "tga"): tga((0, 0, 200, 255))}

    def get(self, name, ext):
        return self.files.get((name, ext))


class MapCache(unittest.TestCase):
    TILES = [(0, 0, 0), (1, 1, 0)]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(M, "MAP_DIR", self.dir)
        self.patch.start()
        self.maps = M.Maps(FakeRes())

    def tearDown(self):
        self.patch.stop()

    def path(self):
        return self.dir / f"{M.Maps.key('tds01', 2, 1, self.TILES)}.png"

    def test_saved_once_without_leftovers(self):
        img = self.maps.image("tds01", 2, 1, self.TILES)
        self.assertEqual(img.size, (2 * M.TILE_PX, M.TILE_PX))
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.path().name])
        self.assertEqual(self.maps.image("tds01", 2, 1, self.TILES).tobytes(), img.tobytes())   # from the cache

    def test_a_half_written_file_is_drawn_again(self):
        good = self.maps.image("tds01", 2, 1, self.TILES)
        self.path().write_bytes(self.path().read_bytes()[:40])       # what the other window was still writing
        again = self.maps.image("tds01", 2, 1, self.TILES)
        self.assertEqual(again.tobytes(), good.tobytes())
        with Image.open(self.path()) as fixed:                       # and the cache is whole again
            self.assertEqual(fixed.size, good.size)

    def test_a_failed_save_still_returns_the_map(self):
        with mock.patch.object(M.os, "replace", side_effect=PermissionError):
            img = self.maps.image("tds01", 2, 1, self.TILES)
        self.assertEqual(img.size, (2 * M.TILE_PX, M.TILE_PX))
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
