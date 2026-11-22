"""Print header bytes of the resource containers and an NWSync blob; list manifests (read-only)."""
import sqlite3
from pathlib import Path

GAME = Path(r"D:\SteamLibrary\steamapps\common\Neverwinter Nights")
NWSYNC = Path.home() / "Documents" / "Neverwinter Nights" / "nwsync"

for p in [GAME / "data" / "nwn_base.key", GAME / "data" / "aurora_tno.bif" if (GAME / "data" / "aurora_tno.bif").exists()
          else next((GAME / "data").glob("*.bif")), GAME / "data" / "txpk" / "Tiles_Tpa.erf"]:
    print(p.name, p.open("rb").read(32))

meta = sqlite3.connect(f"file:{NWSYNC / 'nwsyncmeta.sqlite3'}?mode=ro", uri=True)
for row in meta.execute("select m.sha1, m.origin_url, m.last_used_at, md.module_name from manifests m "
                        "left join manifest_metadata md on md.manifest_sha1 = m.sha1 order by m.last_used_at desc"):
    print("manifest", row)
print("restypes for tno01*:", meta.execute(
    "select distinct resref, restype from manifest_resrefs where resref like 'tno01%' limit 10").fetchall())
print("mi_ sample:", meta.execute(
    "select resref, restype, resref_sha1 from manifest_resrefs where resref like 'mi_tno01%' limit 3").fetchall())
sha = meta.execute("select resref_sha1 from manifest_resrefs where restype = 2013 limit 1").fetchone()[0]
for i in range(6):
    db = sqlite3.connect(f"file:{NWSYNC / f'nwsyncdata_{i}.sqlite3'}?mode=ro", uri=True)
    r = db.execute("select data, size from resrefs where sha1 = ?", (sha,)).fetchone()
    if r:
        print(f"blob in shard {i}: size {r[1]} head {r[0][:24]!r}")
        break
