"""Hostile inputs: map files from other players, server content, the DLL file, shared exports."""
import json
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import db as dbmod, ingame, maps, resources  # noqa: E402


class HostileImports(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(dbmod, "DATA_DIR", self.dir)
        self.p.start()
        self.mine = dbmod.Store(path=self.dir / "mine.sqlite")

    def tearDown(self):
        self.mine.close()
        self.p.stop()

    def evil(self, name="evil.sqlite"):
        """A structurally valid GPS database we then fill with bad values."""
        s = dbmod.Store(path=self.dir / name)
        s.close()
        return self.dir / name

    def test_bad_values_are_rejected_not_imported(self):
        f = self.evil()
        c = sqlite3.connect(f)
        c.execute("INSERT INTO areas(resref,name,width,height) VALUES('huge','Huge',100000,100000)")
        c.execute("INSERT INTO areas(resref,name) VALUES('../../etc','Path')")
        c.execute("INSERT INTO areas(resref,name) VALUES('ok_area', ?)", ("x" * 10_000,))
        c.execute("INSERT INTO pois(area,kind,name,x,y,z) VALUES('ok_area','pin','NaN',?,5,0)", (float("nan"),))
        c.execute("INSERT INTO pois(area,kind,name,x,y,z) VALUES('ok_area','pin','Far',1e12,5,0)")
        c.execute("INSERT INTO pois(area,kind,name,x,y,z) VALUES('ok_area','evil','Kind',5,5,0)")
        c.execute("INSERT INTO pois(area,kind,name,x,y,z) VALUES('ok_area','pin','Fine',5,5,0)")
        c.execute("INSERT INTO transitions(from_area,from_x,from_y,from_z,to_area,to_x,to_y,to_z) "
                  "VALUES('ok_area',?,5,0,'b',1,1,0)", (float("inf"),))
        c.execute("INSERT INTO area_tiles(resref,tileset,width,height,tiles,seen) VALUES('ok_area','tno01',64,64,?,0)", (json.dumps([[1, 0, 0]] * 5),))
        c.execute("INSERT INTO area_tiles(resref,tileset,width,height,tiles,seen) VALUES('big','tno01',1000,1000,'[]',0)")
        c.commit()
        c.close()
        added = self.mine.merge(f)
        self.assertEqual(added["areas"], 2)                         # ok_area, and huge without its size
        a = self.mine.area("ok_area")
        self.assertIsNone(a["name"])                                # 10,000-char name dropped
        self.assertIsNone(self.mine.area("huge")["width"])          # absurd size not trusted
        self.assertIsNone(self.mine.area("../../etc"))
        self.assertEqual(self.mine.stats()["pois"], 1)              # only "Fine"
        self.assertEqual((self.mine.stats()["transitions"], added["tile_layouts"]), (0, 0))
        self.assertGreaterEqual(added["rejected"], 6)

    def test_view_in_place_of_a_table_is_refused(self):
        f = self.dir / "view.sqlite"
        c = sqlite3.connect(f)
        c.execute("CREATE TABLE real_areas(resref, name)")
        c.execute("CREATE VIEW areas AS SELECT * FROM real_areas")
        c.execute("CREATE TABLE pois(x)")
        c.execute("CREATE TABLE transitions(x)")
        c.commit()
        c.close()
        with self.assertRaises(ValueError):
            self.mine.merge(f)

    def test_non_database_and_damaged_files_are_refused(self):
        (self.dir / "text.sqlite").write_text("hello")
        with self.assertRaises(ValueError):
            self.mine.merge(self.dir / "text.sqlite")
        f = self.evil("damaged.sqlite")
        data = bytearray(f.read_bytes())
        data[100:4096] = b"\xff" * (4096 - 100)                     # trash the schema page
        f.write_bytes(bytes(data))
        with self.assertRaises(ValueError):
            self.mine.merge(f)

    def test_shared_export_has_no_play_times(self):
        self.mine.upsert_area("a1", "Market", visit=True)
        self.mine.upsert_poi("a1", "pin", "P", None, 1, 1, 0)
        self.mine.add_transition("a1", (1, 1, 0), "a2", (2, 2, 0))
        out = self.mine.export(self.dir / "share.sqlite", share=True)
        c = sqlite3.connect(out)
        self.assertEqual(c.execute("SELECT first_seen, last_seen, visits FROM areas").fetchone(), (None, None, 0))
        self.assertEqual(c.execute("SELECT first_seen FROM pois").fetchone(), (None,))
        self.assertEqual(c.execute("SELECT last_seen FROM transitions").fetchone(), (None,))
        c.close()
        self.assertIsNotNone(self.mine.area("a1")["first_seen"])    # your own copy keeps them


class ServerContent(unittest.TestCase):
    def test_decompression_bomb_is_refused(self):
        from compression import zstd
        payload = zstd.compress(b"\0" * (resources.MAX_RESOURCE_BYTES + 1))
        blob = b"NSYC" + struct.pack("<III", 3, 2, 100) + struct.pack("<II", 1, 0) + payload   # lies about size
        with self.assertRaises(ValueError):
            resources.nsyc_decode(blob)

    def test_oversized_texture_is_not_decoded(self):
        tga = bytearray(18)
        tga[2] = 2
        struct.pack_into("<HH", tga, 12, 30000, 30000)              # claims 30000x30000
        self.assertFalse(maps.texture_size_ok(bytes(tga)))
        struct.pack_into("<HH", tga, 12, 32, 32)
        self.assertTrue(maps.texture_size_ok(bytes(tga)))

    def test_map_image_refuses_absurd_area(self):
        m = maps.Maps.__new__(maps.Maps)
        with self.assertRaises(ValueError):
            m.image("tno01", 10_000, 10_000, [(1, 0, 0)])


class DllIntegrity(unittest.TestCase):
    def test_tampered_runtime_copy_is_replaced(self):
        folder = Path(tempfile.mkdtemp())
        good = ingame.runtime_dll(folder)
        good.write_bytes(b"MZ not our dll")                         # someone swaps the file
        again = ingame.runtime_dll(folder)
        self.assertEqual(again.read_bytes(), ingame.dll_source().read_bytes())


if __name__ == "__main__":
    unittest.main()
