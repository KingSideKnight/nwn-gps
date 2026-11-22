import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import hotkeys as H  # noqa: E402


class Hotkeys(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(H.parse("Ctrl+Shift+F"), (ord("F"), 3))
        self.assertEqual(H.parse("alt+f5"), (0x74, 4))
        self.assertEqual(H.parse("Ctrl + Alt + 7"), (ord("7"), 6))
        for bad in ("F", "Ctrl+", "Win+F", "Ctrl+Space", "Ctrl+F13"):
            with self.assertRaises(ValueError, msg=bad):
                H.parse(bad)

    def test_resolve_falls_back_on_bad_and_duplicate(self):
        warnings = []
        r = H.resolve({"search": "Alt+S", "clear": "nonsense", "map": "Alt+S"}, warn=warnings.append)
        self.assertEqual(r["search"][:2], (ord("S"), 4))
        self.assertEqual(r["clear"][2], "Ctrl+Shift+X")             # invalid -> default
        self.assertEqual(r["map"][2], "Ctrl+Shift+M")               # duplicate of search -> default
        self.assertEqual(len(warnings), 2)

    def test_table_layout_matches_dll_order(self):
        r = H.resolve({})
        t = H.table_bytes(r)
        self.assertEqual(len(t), 6 * 8)
        self.assertEqual(struct.unpack_from("<II", t, 0), (ord("F"), 3))      # HK_SEARCH first
        self.assertEqual(struct.unpack_from("<II", t, 5 * 8), (ord("I"), 3))  # HK_IMPORT last

    def test_legend_groups_common_modifiers(self):
        rows = H.legend_rows(H.resolve({}))
        self.assertEqual(rows[0][0], "Ctrl+Shift")
        self.assertEqual(rows[0][1][0], ("F", "Search"))
        mixed = H.legend_rows(H.resolve({"hide": "Alt+H"}))
        self.assertIsNone(mixed[0][0])                               # mixed modifiers: full combos
        self.assertIn(("Alt+H", "Hide"), mixed[0][1])


if __name__ == "__main__":
    unittest.main()
