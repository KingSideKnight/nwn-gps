"""Does the Arelith NWSync manifest carry module contents (areas .are, .git, .ifo)? Read-only."""
import sqlite3
from pathlib import Path

NWSYNC = Path.home() / "Documents" / "Neverwinter Nights" / "nwsync"
meta = sqlite3.connect(f"file:{NWSYNC / 'nwsyncmeta.sqlite3'}?mode=ro", uri=True)
cols = [r[1] for r in meta.execute("PRAGMA table_info(manifest_metadata)")]
print("manifest_metadata columns:", cols)
for row in meta.execute("SELECT * FROM manifest_metadata"):
    d = dict(zip(cols, row))
    print({k: (str(v)[:60] if v is not None else None) for k, v in d.items()
           if k in ("manifest_sha1", "module_name", "includes_module_contents", "includes_client_contents", "group_id")})
man = meta.execute("select sha1 from manifests where origin_url like '%nwnarelith%' order by last_used_at desc").fetchone()[0]
print("arelith manifest", man)
for rtype, name in ((2012, "are"), (2023, "git"), (2014, "ifo"), (2013, "set"), (2002, "mdl"), (3, "tga"), (2033, "dds")):
    n = meta.execute("select count(*) from manifest_resrefs where manifest_sha1=? and restype=?", (man, rtype)).fetchone()[0]
    print(f"  .{name}: {n}")
print("sample areas-ish resrefs:", meta.execute(
    "select resref from manifest_resrefs where manifest_sha1=? and resref like 'ir_%' limit 10", (man,)).fetchall())
