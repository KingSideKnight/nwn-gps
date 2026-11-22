"""Guard against UTF-8 text that was decoded as ANSI and saved again (an em dash turning into
three Latin-1 characters, for example)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOJIBAKE = re.compile("[ÂÃ][\u0080-¿]|â[\u0080-€][\u0080-¿‘-›]")


class SourceEncoding(unittest.TestCase):
    def test_no_mojibake(self):
        bad = []
        for pattern in ("nwngps/*.py", "native/*.c", "*.md", "*.txt", "tests/*.py", "packaging/*.py"):
            for f in ROOT.glob(pattern):
                for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
                    if MOJIBAKE.search(line):
                        bad.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_sources_are_valid_utf8(self):
        for f in list(ROOT.glob("nwngps/*.py")) + list(ROOT.glob("native/*.c")):
            f.read_bytes().decode("utf-8")      # raises if not


if __name__ == "__main__":
    unittest.main()
