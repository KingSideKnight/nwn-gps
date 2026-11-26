"""The map window: where it opens on different monitor setups, frame sizes, and its drawing."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import mapwindow as M  # noqa: E402
from nwngps.nav import Guidance  # noqa: E402


def mon(l, t, r, b, primary=False, taskbar=40):
    return {"screen": (l, t, r, b), "work": (l, t, r, b - taskbar), "primary": primary}


ONE = [mon(0, 0, 1920, 1080, True)]
TWO = [mon(0, 0, 2560, 1440, True), mon(2560, 0, 4608, 1536)]           # second monitor to the right
LEFT = [mon(0, 0, 1920, 1080, True), mon(-1280, 200, 0, 1224)]           # second one left of the primary
STACKED = [mon(0, 0, 1920, 1080, True), mon(0, -1080, 1920, 0)]          # one above the other
THREE = [mon(0, 0, 1920, 1080, True), mon(1920, 0, 3840, 1080), mon(-2560, 0, 0, 1440)]
PORTRAIT = [mon(0, 0, 1920, 1080, True), mon(1920, 0, 3000, 1920)]       # a monitor turned on its side


def inside(x, y, m):
    l, t, r, b = m["work"]
    return l <= x < r and t <= y < b


class Placement(unittest.TestCase):
    def test_one_monitor_opens_a_window_not_covering_everything(self):
        x, y, w, h, zoomed = M.place({}, ONE)
        self.assertFalse(zoomed)
        self.assertTrue(inside(x, y, ONE[0]) and w < 1920 and h < 1040)

    def test_fills_a_monitor_the_game_isnt_on(self):
        for mons in (TWO, LEFT, STACKED, PORTRAIT):
            x, y, w, h, zoomed = M.place({}, mons, game=mons[0]["screen"])
            self.assertTrue(zoomed, mons)
            self.assertTrue(inside(x, y, mons[1]), mons)

    def test_game_on_the_second_monitor(self):
        x, y, *_ = M.place({}, TWO, game=TWO[1]["screen"])
        self.assertTrue(inside(x, y, TWO[0]))

    def test_three_monitors_picks_the_biggest_free_one(self):
        x, y, *_ = M.place({}, THREE, game=THREE[0]["screen"])
        self.assertTrue(inside(x, y, THREE[2]))

    def test_game_not_running_yet_avoids_the_primary(self):
        x, y, *_ = M.place({}, TWO)
        self.assertTrue(inside(x, y, TWO[1]))

    def test_remembers_where_you_put_it(self):
        saved = {"x": 2700, "y": 100, "w": 900, "h": 600, "zoomed": False}
        self.assertEqual(M.place(saved, TWO, game=TWO[0]["screen"]), (2700, 100, 900, 600, False))

    def test_saved_spot_on_an_unplugged_monitor_is_ignored(self):
        saved = {"x": 2700, "y": 100, "w": 900, "h": 600, "zoomed": True}
        x, y, w, h, zoomed = M.place(saved, ONE)
        self.assertTrue(inside(x, y, ONE[0]) and not zoomed)

    def test_bad_saved_values_are_ignored(self):
        for saved in ({"x": "a"}, {"x": 1, "y": 1, "w": 5, "h": 5}, {"x": None, "y": 0, "w": 900, "h": 600}):
            x, y, *_ = M.place(saved, ONE)
            self.assertTrue(inside(x, y, ONE[0]))

    def test_no_monitors_reported(self):
        self.assertEqual(len(M.place({}, [])), 5)


class Frames(unittest.TestCase):
    def test_display_scale_makes_text_bigger(self):
        self.assertEqual(M.frame_for(1500, 1000, 1.5), (1000, 666))

    def test_huge_windows_are_capped(self):
        w, h = M.frame_for(3840, 2160)
        self.assertLessEqual(max(w, h), M.MAX_FRAME)
        self.assertAlmostEqual(w / h, 3840 / 2160, places=2)

    def test_tiny_windows_get_a_minimum(self):
        self.assertEqual(M.frame_for(10, 10), (M.MIN_W, M.MIN_H))


class Drawing(unittest.TestCase):
    def test_directions_bar_states(self):
        from PIL import Image
        for g in (None,
                  Guidance("NAV", dest_name="Bank", line1="Walk to the north door", line2="then 2 more areas",
                           distance=42.0, bearing=10.0, relative=-30.0),
                  Guidance("ARRIVED", dest_name="Bank", line1="You're there"),
                  Guidance("NO_ROUTE", dest_name="Bank", line1="No known route yet")):
            img = Image.new("RGBA", (1000, 600))
            M.directions_bar(img, g, "Ctrl+Shift+F")
            self.assertEqual(img.getpixel((2, 2)), M.BAR_BG)

    def test_message_frame(self):
        self.assertEqual(M.message_frame((800, 500), "Waiting for the game...").size, (800, 500))


class Clicks(unittest.TestCase):
    def test_click_below_the_bar_goes_to_the_map(self):
        w = M.Worker()
        seen = []
        w.fm = SimpleNamespace(pick_at=lambda fx, fy: seen.append((fx, fy)))
        w.inputs.put(("click", 100, M.BAR + 50))
        w.handle_inputs(None)
        self.assertEqual(seen, [(100, 50)])


if __name__ == "__main__":
    unittest.main()
