"""Settings window logic (the window itself is a thin tkinter layer over these)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import config, settings_window as SW  # noqa: E402


def form(**changes):
    v = {"hotkeys": dict(config.DEFAULT_HOTKEYS), "game_dir": "", "user_dir": "", "death_areas": "fugue, afterlife",
         "check_updates": True, "dm_mode": False}
    v.update(changes)
    return v


class KeyText(unittest.TestCase):
    def test_names(self):
        self.assertEqual(SW.key_text(ord("F"), 3), "Ctrl+Shift+F")
        self.assertEqual(SW.key_text(0x74, 4), "Alt+F5")
        self.assertEqual(SW.key_text(ord("7"), 6), "Ctrl+Alt+7")

    def test_unusable(self):
        self.assertIsNone(SW.key_text(ord("F"), 0))          # needs a modifier
        self.assertIsNone(SW.key_text(0x20, 2))              # space
        self.assertIsNone(SW.key_text(0x7C, 2))              # F13


class Validate(unittest.TestCase):
    def test_good_form_keeps_other_settings(self):
        base = config.load_settings()
        base["accepted_notice"] = True
        out, problems = SW.validate(form(), base)
        self.assertEqual(problems, [])
        self.assertTrue(out["accepted_notice"])
        self.assertEqual(out["death_areas"], ["fugue", "afterlife"])
        self.assertEqual(out["hotkeys"], config.DEFAULT_HOTKEYS)

    def test_duplicate_keys_and_bad_folders_are_refused(self):
        keys = dict(config.DEFAULT_HOTKEYS, map="Ctrl+Shift+F")
        _, problems = SW.validate(form(hotkeys=keys, game_dir=tempfile.mkdtemp(),
                                       user_dir=str(Path(tempfile.mkdtemp()) / "missing")), config.load_settings())
        self.assertEqual(len(problems), 3)
        self.assertIn("Ctrl+Shift+F is used for both", problems[0])


if __name__ == "__main__":
    unittest.main()
