"""RTSS slot handling against a fake shared-memory block laid out like RTSSSharedMemory.h v2.20."""
import ctypes
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import rtss as R  # noqa: E402
from nwngps.hud import render, turn_glyph  # noqa: E402

ENTRY = 256 + 256 + 4096 + 262144 + 32768
N, ARR_OFF = 8, 0x100


class FakeRTSS(R.RTSS):
    def __init__(self):
        super().__init__()
        self.mem = ctypes.create_string_buffer(ARR_OFF + N * ENTRY)
        struct.pack_into("<IIIIIIIIIi", self.mem, 0, R.SIG_RTSS, 0x20014, 0, 0, 0, ENTRY, ARR_OFF, N, 0, 0)

    def connect(self):
        self.view = ctypes.addressof(self.mem)
        return True

    def entry(self, i):
        return self.view + ARR_OFF + i * ENTRY


class Slots(unittest.TestCase):
    def test_claims_free_slot_skipping_rtss_entry_and_others(self):
        f = FakeRTSS()
        f.connect()
        ctypes.memmove(f.entry(1) + R.E_OWNER, b"Afterburner\0", 12)
        self.assertTrue(f.show("hello"))
        self.assertEqual(f._owner(f.entry(2)), R.OWNER)
        self.assertEqual(ctypes.string_at(f.entry(2) + R.E_OSDEX), b"hello")
        self.assertEqual(struct.unpack_from("<I", f.mem, R.H_OSD_FRAME)[0], 1)
        f.show("again")
        self.assertEqual(ctypes.string_at(f.entry(2) + R.E_OSDEX), b"again")

    def test_busy_flag_skips_and_is_left_clear(self):
        f = FakeRTSS()
        f.connect()
        struct.pack_into("<i", f.mem, R.H_BUSY, 1)
        self.assertFalse(f.show("x"))
        struct.pack_into("<i", f.mem, R.H_BUSY, 0)
        self.assertTrue(f.show("x"))
        self.assertEqual(struct.unpack_from("<i", f.mem, R.H_BUSY)[0], 0)

    def test_clear_releases_slot(self):
        f = FakeRTSS()
        f.connect()
        f.show("x")
        f.clear()
        self.assertEqual(f._owner(f.entry(1)), b"")


class Render(unittest.TestCase):
    def test_glyphs(self):
        self.assertEqual([turn_glyph(a) for a in (0, 90, 180, -90, 45)], ["^^", ">>", "vv", "<<", "^>"])

    def test_nav_text(self):
        from nwngps.nav import Guidance
        from nwngps.session import Snapshot
        g = Guidance("NAV", dest_name="Shop", line1="Take the exit", distance=42.4, bearing=90.0, relative=-90.0)
        t = render(g, Snapshot("IN_GAME"))
        self.assertIn("<< 42 m", t)
        self.assertIn("left 90", t)
        self.assertIn("Take the exit", t)


if __name__ == "__main__":
    unittest.main()
