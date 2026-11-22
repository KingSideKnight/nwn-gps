"""Survey: key files in the install, NWSync sqlite schemas and a few sample rows (read-only)."""
import sqlite3
from pathlib import Path

GAME = Path(r"D:\SteamLibrary\steamapps\common\Neverwinter Nights")
NWSYNC = Path.home() / "Documents" / "Neverwinter Nights" / "nwsync"

print("key files:", [p.name for p in (GAME / "data").glob("*.key")])
print("bif count:", len(list((GAME / "data").glob("*.bif"))))
for f in ("nwsyncmeta.sqlite3", "nwsyncdata_0.sqlite3"):
    c = sqlite3.connect(f"file:{NWSYNC / f}?mode=ro", uri=True)
    for name, sql in c.execute("select name, sql from sqlite_master where type='table'"):
        n = c.execute(f"select count(*) from {name}").fetchone()[0]
        print(f"{f}: {name} ({n} rows)\n    {sql[:300]}")
    c.close()
