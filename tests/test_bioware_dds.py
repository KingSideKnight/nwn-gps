"""NWN's own DDS variant (custom tilesets such as Arelith's tdm01) must decode like a real DDS."""
import io
import struct
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import maps  # noqa: E402


def bioware(w, h, channels, level0, extra=b""):
    return struct.pack("<4If", w, h, channels, len(level0), 1.0) + level0 + extra


# one DXT1 block: colour0 = pure red (565), colour1 = black, all pixels index 0
RED_BLOCK = struct.pack("<HHI", 0xF800, 0x0000, 0)


class BiowareDds(unittest.TestCase):
    def test_dxt1_decodes(self):
        data = bioware(8, 8, 3, RED_BLOCK * 4, extra=RED_BLOCK + RED_BLOCK)   # plus mip levels
        dds = maps.bioware_dds(data)
        self.assertTrue(maps.texture_size_ok(dds))
        img = Image.open(io.BytesIO(dds)).convert("RGBA")
        self.assertEqual(img.size, (8, 8))
        self.assertEqual(img.getpixel((3, 5))[:3], (255, 0, 0))

    def test_dxt5_header(self):
        dds = maps.bioware_dds(bioware(4, 4, 4, b"\0" * 16))
        self.assertEqual(dds[84:88], b"DXT5")
        Image.open(io.BytesIO(dds)).load()

    def test_rejects_other_data(self):
        self.assertIsNone(maps.bioware_dds(b"DDS " + b"\0" * 200))         # already standard
        self.assertIsNone(maps.bioware_dds(bioware(8, 8, 5, RED_BLOCK * 4)))   # bad channel count
        self.assertIsNone(maps.bioware_dds(bioware(8, 8, 3, RED_BLOCK * 3)))   # size doesn't match
        self.assertIsNone(maps.bioware_dds(bioware(8, 8, 3, RED_BLOCK * 4)[:40]))   # truncated
        self.assertIsNone(maps.bioware_dds(bioware(4096, 4096, 3, b"")))     # giant
        self.assertIsNone(maps.bioware_dds(b"short"))


if __name__ == "__main__":
    unittest.main()
