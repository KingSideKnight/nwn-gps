"""Each CLI command runs only its own branch (guards against dispatch mistakes)."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import cli, db as dbmod, hud  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["cli", *argv]), redirect_stdout(out):
        try:
            cli.main()
        except SystemExit as e:
            out.write(f"<exit {e.code}>")
    return out.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(dbmod, "DATA_DIR", self.dir), mock.patch.object(hud, "DATA_DIR", self.dir),
                        mock.patch.object(hud, "TARGET_FILE", self.dir / "nav_target.json")]
        for p in self.patches:
            p.start()
        s = dbmod.Store()
        s.upsert_area("a1", "Market Square", "t", 10, 10)
        s.upsert_poi("a1", "pin", "City Gates", None, 10, 10, 0)
        s.close()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_go_sets_and_clears_target(self):
        self.assertIn("destination: City Gates", run("go", "gates"))
        self.assertEqual(hud.read_target()["query"], "gates")
        self.assertIn("destination cleared", run("go", "--stop"))
        self.assertIsNone(hud.read_target())

    def test_merge_does_not_touch_destination(self):
        share = self.dir / "Exports" / "share.sqlite"      # exports live outside the data folder
        run("export", str(share))
        out = run("merge", str(share), "--dry-run")
        self.assertIn("Would add", out)
        self.assertNotIn("nothing matches", out)
        self.assertIsNone(hud.read_target())
        out = run("merge", str(share))
        self.assertIn("backup:", out)
        self.assertNotIn("<exit", out)
        self.assertTrue(list((self.dir / "backups").glob("*before-merge*.sqlite")))

    def test_find(self):
        self.assertIn("City Gates", run("find", "gate"))


if __name__ == "__main__":
    unittest.main()
