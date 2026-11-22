"""One-off: tag rows recorded before server tracking existed (all from ARE_CitiesAndPlanes)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps.db import Store  # noqa: E402

s = Store()
s.db.execute("UPDATE areas SET server='ARE_CitiesAndPlanes' WHERE server IS NULL")
s.db.execute("UPDATE transitions SET from_server='ARE_CitiesAndPlanes', to_server='ARE_CitiesAndPlanes' "
             "WHERE from_server IS NULL")
s.commit()
print(s.path.name, s.stats())
s.close()
