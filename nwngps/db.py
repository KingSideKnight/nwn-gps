"""SQLite storage for areas, points of interest and transitions.

Database file: <project>/data/<module>.sqlite (git-ignored; back it up by copying the file).
"""
import math
import sqlite3
import time
from pathlib import Path

from .config import DATA_DIR  # %LOCALAPPDATA%\\NWN GPS (see config.py)

SCHEMA = """
CREATE TABLE IF NOT EXISTS areas (
    resref      TEXT PRIMARY KEY,
    name        TEXT,
    tileset     TEXT,
    width       INTEGER,
    height      INTEGER,
    first_seen  REAL,
    last_seen   REAL,
    visits      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pois (
    id          INTEGER PRIMARY KEY,
    area        TEXT NOT NULL REFERENCES areas(resref),
    kind        TEXT NOT NULL,          -- pin | door | user
    name        TEXT,
    tag         TEXT,
    x REAL, y REAL, z REAL,
    first_seen  REAL,
    last_seen   REAL
);
CREATE INDEX IF NOT EXISTS pois_area ON pois(area);
CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY,
    from_area   TEXT NOT NULL,
    from_x REAL, from_y REAL, from_z REAL,
    to_area     TEXT NOT NULL,
    to_x REAL, to_y REAL, to_z REAL,
    via_poi     INTEGER REFERENCES pois(id),   -- nearest pin/door at the exit point
    count       INTEGER DEFAULT 1,
    first_seen  REAL,
    last_seen   REAL
);
CREATE INDEX IF NOT EXISTS trans_from ON transitions(from_area);
CREATE TABLE IF NOT EXISTS area_tiles (
    resref      TEXT PRIMARY KEY,
    tileset     TEXT,
    width       INTEGER,
    height      INTEGER,
    tiles       TEXT,       -- JSON [[tile_id, orientation, height], ...] row-major from the SW corner
    seen        REAL
);
"""

# Columns added after the first schema; applied with ALTER TABLE when missing.
MIGRATIONS = {
    "areas": {"server": "TEXT"},
    "transitions": {"from_server": "TEXT", "to_server": "TEXT",
                    "kind": "TEXT DEFAULT 'walk'",       # walk | portal (server change)
                    "confirmed": "INTEGER DEFAULT 1"},   # 0 = portal seen once across a menu visit
}


def db_name(world):
    return "".join(c if c.isalnum() else "_" for c in world.lower())

POI_MERGE_DIST = 2.0      # metres: same kind+name closer than this = same POI
TRANS_MERGE_DIST = 5.0    # metres: same from/to areas with exits this close = same transition
VIA_MAX_DIST = 6.0        # metres: a pin/door this close to an exit labels the transition


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


LEGACY_DATA = Path(__file__).resolve().parent.parent / "data"     # before release prep


def migrate_legacy(log=print):
    """One-time: copy data from the old <project>/data folder into DATA_DIR. Copies, never moves:
    the old folder is left as it was (rollback = delete DATA_DIR)."""
    if not LEGACY_DATA.is_dir() or LEGACY_DATA.resolve() == DATA_DIR.resolve():
        return False
    marker = DATA_DIR / ".migrated_from_project"
    if marker.exists():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for db in LEGACY_DATA.glob("*.sqlite"):
        dest = DATA_DIR / db.name
        if not dest.exists():
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            out = sqlite3.connect(dest)
            with out:
                src.backup(out)
            src.close()
            out.close()
            copied.append(db.name)
    import shutil
    for name in ("recent.json", "ui.json", "nav_target.json"):
        if (LEGACY_DATA / name).exists() and not (DATA_DIR / name).exists():
            shutil.copy2(LEGACY_DATA / name, DATA_DIR / name)
            copied.append(name)
    if (LEGACY_DATA / "maps").is_dir() and not (DATA_DIR / "maps").exists():
        shutil.copytree(LEGACY_DATA / "maps", DATA_DIR / "maps")
        copied.append("maps/")
    marker.write_text(str(LEGACY_DATA))
    if copied:
        log(f"copied your existing data from {LEGACY_DATA} to {DATA_DIR}: {', '.join(copied)}")
    return bool(copied)


def latest_world():
    """World of the most recently used map database (for the command line), or None.
    Only databases the GPS keeps for a world count (not copies someone dropped in the folder)."""
    dbs = [p for p in DATA_DIR.glob("*.sqlite") if not p.stem.endswith(("-share", "preview"))] \
        if DATA_DIR.exists() else []
    dbs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dbs[0].stem if dbs else None


class Store:
    def __init__(self, world=None, path=None):
        """world: e.g. 'nwnarelith.com' (from the server's NWSync host). None = the most recently
        used world (handy for the command line)."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.world = world or latest_world() or "unknown"
        world = self.world
        self.path = Path(path) if path else DATA_DIR / f"{db_name(world)}.sqlite"
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        # WAL: the recorder writes while the GPS/CLI read, and commits stay cheap (big merges)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.db.commit()

    @staticmethod
    def worlds():
        return sorted(p.stem for p in DATA_DIR.glob("*.sqlite")) if DATA_DIR.exists() else []

    def close(self):
        self.db.commit()
        self.db.close()

    # --- writes -------------------------------------------------------------
    def upsert_area(self, resref, name, tileset=None, width=None, height=None, visit=False, server=None):
        now = time.time()
        self.db.execute(
            """INSERT INTO areas(resref,name,tileset,width,height,first_seen,last_seen,visits,server)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(resref) DO UPDATE SET
                 name=COALESCE(excluded.name,name), tileset=COALESCE(excluded.tileset,tileset),
                 width=COALESCE(excluded.width,width), height=COALESCE(excluded.height,height),
                 server=COALESCE(excluded.server,server),
                 last_seen=excluded.last_seen, visits=visits+?""",
            (resref, name, tileset, width, height, now, now, int(visit), server, int(visit)))
        self.db.commit()

    def upsert_poi(self, area, kind, name, tag, x, y, z):
        now = time.time()
        for r in self.db.execute("SELECT id,x,y FROM pois WHERE area=? AND kind=? AND name IS ? AND tag IS ?",
                                 (area, kind, name, tag)):
            if dist(r["x"], r["y"], x, y) < POI_MERGE_DIST:
                self.db.execute("UPDATE pois SET last_seen=? WHERE id=?", (now, r["id"]))
                return r["id"]
        cur = self.db.execute(
            "INSERT INTO pois(area,kind,name,tag,x,y,z,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?)",
            (area, kind, name, tag, x, y, z, now, now))
        return cur.lastrowid

    def nearest_poi(self, area, x, y, max_dist=VIA_MAX_DIST):
        best = None
        for r in self.db.execute("SELECT * FROM pois WHERE area=? AND kind IN ('pin','door')", (area,)):
            d = dist(r["x"], r["y"], x, y)
            # prefer pins (Arelith marks transitions with them) when distances are similar
            score = d - (1.0 if r["kind"] == "pin" else 0.0)
            if d <= max_dist and (best is None or score < best[0]):
                best = (score, r)
        return best[1] if best else None

    def add_transition(self, from_area, fpos, to_area, tpos, from_server=None, to_server=None,
                       kind="walk", confirmed=True):
        """Record (or re-confirm) an edge. Seeing an unconfirmed portal a second time confirms it."""
        now = time.time()
        for r in self.db.execute("SELECT * FROM transitions WHERE from_area=? AND to_area=?", (from_area, to_area)):
            if dist(r["from_x"], r["from_y"], fpos[0], fpos[1]) < TRANS_MERGE_DIST:
                self.db.execute("UPDATE transitions SET count=count+1, last_seen=?, confirmed=1 WHERE id=?",
                                (now, r["id"]))
                self.db.commit()
                return r["id"], False
        via = self.nearest_poi(from_area, fpos[0], fpos[1])
        cur = self.db.execute(
            """INSERT INTO transitions(from_area,from_x,from_y,from_z,to_area,to_x,to_y,to_z,via_poi,first_seen,last_seen,
                                       from_server,to_server,kind,confirmed)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (from_area, *fpos, to_area, *tpos, via["id"] if via else None, now, now,
             from_server, to_server, kind, int(confirmed)))
        self.db.commit()
        return cur.lastrowid, True

    def commit(self):
        self.db.commit()

    def save_tiles(self, resref, tileset, w, h, tiles):
        import json
        self.db.execute("INSERT OR REPLACE INTO area_tiles(resref,tileset,width,height,tiles,seen) VALUES(?,?,?,?,?,?)",
                        (resref, tileset, w, h, json.dumps(tiles), time.time()))
        self.db.commit()

    def tiles(self, resref):
        import json
        r = self.db.execute("SELECT * FROM area_tiles WHERE resref=?", (resref,)).fetchone()
        return (r["tileset"], r["width"], r["height"], [tuple(t) for t in json.loads(r["tiles"])]) if r else None

    # --- reads --------------------------------------------------------------
    def area(self, resref):
        return self.db.execute("SELECT * FROM areas WHERE resref=?", (resref,)).fetchone()

    def area_name(self, resref):
        a = self.area(resref)
        return (a["name"] if a and a["name"] else resref)

    def search(self, text, limit=20):
        like = f"%{text}%"
        areas = self.db.execute(
            "SELECT 'area' AS kind, resref AS area, name, NULL AS x, NULL AS y FROM areas "
            "WHERE name LIKE ? OR resref LIKE ? ORDER BY visits DESC LIMIT ?", (like, like, limit)).fetchall()
        pois = self.db.execute(
            "SELECT p.kind, p.area, p.name || COALESCE(' ['||p.tag||']','') AS name, p.x, p.y FROM pois p "
            "WHERE (p.name LIKE ? OR p.tag LIKE ?) AND p.name NOT IN ('Door','Window') LIMIT ?",
            (like, like, limit)).fetchall()
        return list(areas) + list(pois)

    def transitions(self, include_unconfirmed=False):
        q = "SELECT * FROM transitions" + ("" if include_unconfirmed else " WHERE confirmed=1")
        return self.db.execute(q).fetchall()

    def poi(self, pid):
        return self.db.execute("SELECT * FROM pois WHERE id=?", (pid,)).fetchone()

    # --- sharing ------------------------------------------------------------
    def export(self, dest):
        """Consistent copy of this database (safe while the recorder is writing)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(dest)
        with out:
            self.db.backup(out)
        out.close()
        return dest

    def backup(self, tag="backup"):
        return self.export(DATA_DIR / "backups" / f"{self.path.stem}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")

    def merge(self, other_path):
        """Merge another player's database into this one. Areas fill in missing details, POIs and
        transitions are de-duplicated by distance, tile layouts are added where we have none.
        Returns counts of what was added. (For a dry run, merge into an export() copy.)"""
        other = sqlite3.connect(f"file:{Path(other_path)}?mode=ro", uri=True)
        other.row_factory = sqlite3.Row
        tables = {r[0] for r in other.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "areas" not in tables:
            raise ValueError(f"{other_path} is not an NWN GPS database")
        added = {"areas": 0, "areas_updated": 0, "pois": 0, "transitions": 0, "transitions_seen_again": 0,
                 "tile_layouts": 0}
        try:
            for r in other.execute("SELECT * FROM areas"):
                r = dict(r)
                mine = self.area(r["resref"])
                if mine is None:
                    added["areas"] += 1
                elif any(mine[k] is None and r.get(k) is not None for k in ("name", "tileset", "width", "height")):
                    added["areas_updated"] += 1
                self.db.execute(
                    """INSERT INTO areas(resref,name,tileset,width,height,first_seen,last_seen,visits,server)
                       VALUES(?,?,?,?,?,?,?,0,?)
                       ON CONFLICT(resref) DO UPDATE SET
                         name=COALESCE(name,excluded.name), tileset=COALESCE(tileset,excluded.tileset),
                         width=COALESCE(width,excluded.width), height=COALESCE(height,excluded.height),
                         server=COALESCE(server,excluded.server),
                         first_seen=MIN(first_seen,excluded.first_seen)""",
                    (r["resref"], r.get("name"), r.get("tileset"), r.get("width"), r.get("height"),
                     r.get("first_seen"), r.get("last_seen"), r.get("server")))
            before = self.stats()["pois"]
            for r in other.execute("SELECT * FROM pois"):
                self.upsert_poi(r["area"], r["kind"], r["name"], r["tag"], r["x"], r["y"], r["z"])
            added["pois"] = self.stats()["pois"] - before
            for r in other.execute("SELECT * FROM transitions"):
                r = dict(r)
                _, new = self.add_transition(r["from_area"], (r["from_x"], r["from_y"], r["from_z"]),
                                             r["to_area"], (r["to_x"], r["to_y"], r["to_z"]),
                                             r.get("from_server"), r.get("to_server"), r.get("kind") or "walk",
                                             bool(r.get("confirmed", 1)))
                added["transitions" if new else "transitions_seen_again"] += 1
            if "area_tiles" in tables:
                for r in other.execute("SELECT * FROM area_tiles"):
                    if not self.db.execute("SELECT 1 FROM area_tiles WHERE resref=?", (r["resref"],)).fetchone():
                        self.db.execute("INSERT INTO area_tiles(resref,tileset,width,height,tiles,seen) "
                                        "VALUES(?,?,?,?,?,?)", tuple(r))
                        added["tile_layouts"] += 1
            self.db.commit()
        finally:
            other.close()
        return added

    def stats(self):
        q = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {"areas": q("areas"), "pois": q("pois"), "transitions": q("transitions")}
