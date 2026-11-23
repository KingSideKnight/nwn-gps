import os
import unittest

from nwngps import memory


class ModuleListTest(unittest.TestCase):
    def test_own_process(self):
        names = [n.lower() for n, _ in memory.modules(os.getpid())]
        self.assertIn("kernel32.dll", names)

    def test_missing_process_is_empty_not_a_crash(self):
        # A failed snapshot returns INVALID_HANDLE_VALUE; it used to reach Module32FirstW and raise
        # "OverflowError: int too long to convert" while the game was starting.
        self.assertEqual(memory.modules(0x7FFFFFF0), [])

    def test_invalid_handle_constant(self):
        self.assertEqual(memory.INVALID_HANDLE, 2 ** 64 - 1)


if __name__ == "__main__":
    unittest.main()
