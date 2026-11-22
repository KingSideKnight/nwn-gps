import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nwngps.single import single_instance  # noqa: E402

CHILD = "import sys; sys.path.insert(0, r'%s'); from nwngps.single import single_instance; " \
        "single_instance('unittest'); print('second copy ran')" % ROOT


class SingleInstance(unittest.TestCase):
    def test_second_copy_is_refused(self):
        single_instance("unittest")
        r = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True)
        self.assertNotIn("second copy ran", r.stdout)
        self.assertIn("already running", r.stderr)


if __name__ == "__main__":
    unittest.main()
