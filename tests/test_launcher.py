"""Launcher: children start from the app folder and a part that keeps crashing is given up on."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import config, launcher  # noqa: E402


class FakeProc:
    def __init__(self, code=1):
        self.returncode, self.started_at = code, time.time()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class Launcher(unittest.TestCase):
    def test_child_runs_from_app_folder(self):
        with mock.patch.object(launcher.subprocess, "Popen") as popen, \
             mock.patch.object(config, "LOG_DIR", Path(tempfile.mkdtemp())):
            launcher.start("recorder")
        self.assertEqual(popen.call_args.kwargs["cwd"], config.app_dir())

    def test_gives_up_after_repeated_startup_crashes(self):
        logs = Path(tempfile.mkdtemp())
        (logs / "crash-recorder.log").write_text("ModuleNotFoundError: No module named 'PIL'\n")
        out = []
        with mock.patch.object(config, "LOG_DIR", logs), \
             mock.patch.object(launcher, "start", lambda part: FakeProc()), \
             mock.patch.object(launcher, "first_run_notice", lambda: True), \
             mock.patch.object(launcher, "RESTART_DELAY", 0), \
             mock.patch.object(launcher.time, "sleep", lambda s: None), \
             mock.patch.object(config, "game_dir", lambda *a: None), \
             mock.patch("nwngps.single.single_instance", lambda name: None), \
             mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))):
            launcher.main()
        text = "\n".join(out)
        self.assertIn("won't be restarted", text)
        self.assertIn("No module named 'PIL'", text)
        self.assertIn("Nothing left running", text)


if __name__ == "__main__":
    unittest.main()


class JobObjectTest(unittest.TestCase):
    def test_child_dies_with_job(self):
        import subprocess, sys
        from nwngps import launcher
        assign = launcher.kill_with_launcher_job()
        self.assertIsNotNone(assign)
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertTrue(assign(p))
        finally:
            p.kill()
            p.wait()
