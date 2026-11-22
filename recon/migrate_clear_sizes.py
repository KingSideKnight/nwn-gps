"""One-off: area sizes recorded before 2026-11-22 13:15 came from a wrong offset (+0x2A0).
Clear them; the recorder refills them on the next visit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps.db import Store  # noqa: E402

s = Store()
n = s.db.execute("UPDATE areas SET width=NULL, height=NULL WHERE width=10 AND height=10").rowcount
s.commit()
print(f"cleared {n} sizes")
s.close()
