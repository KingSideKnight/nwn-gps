"""SQLite storage for areas, points of interest and transitions.

Database file: <project>/data/<module>.sqlite (git-ignored; back it up by copying the file).
"""
import math
import re
import sqlite3
import time
from pathlib import Path

from .config import DATA_DIR  # Documents\\NWN GPS\\data (see config.py)

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


# ---- untrusted input (maps imported from other players) -----------------------------------
MAX_IMPORT_BYTES = 512 * 1024 * 1024
MAX_ROWS = {"areas": 50_000, "pois": 2_000_000, "transitions": 500_000, "area_tiles": 50_000}
MAX_TILES = 64                      # NWN areas are at most 32x32 tiles; allow headroom
MAX_COORD = MAX_TILES * 10 + 50     # metres
RESREF = re.compile(r"^[A-Za-z0-9_]{1,32}$")
REQUIRED_TABLES = ("areas", "pois", "transitions")


def open_untrusted(path):
    """Open another player's database safely: read-only, defensive mode (no writes to the schema,
    no dangerous pragmas), untrusted schema (no functions in views/triggers), integrity-checked,
    and the expected objects must be real tables (not views)."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path.name}: not a file")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError(f"{path.name}: too large to be a GPS map ({path.stat().st_size // 2**20} MB)")
    with open(path, "rb") as f:
        if f.read(16) != b"SQLite format 3\0":
            raise ValueError(f"{path.name} is not an NWN GPS map file")
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        if hasattr(con, "setconfig"):
            con.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
            con.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("PRAGMA query_only=ON")
        kinds = dict(con.execute("SELECT name, type FROM sqlite_master WHERE name IN (?,?,?,?)",
                                 (*REQUIRED_TABLES, "area_tiles")).fetchall())
        if any(kinds.get(t) != "table" for t in REQUIRED_TABLES) or kinds.get("area_tiles", "table") != "table":
            raise ValueError(f"{path.name} is not an NWN GPS map file")
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError(f"{path.name} is damaged (integrity check failed)")
    except sqlite3.DatabaseError as e:
        con.close()
        raise ValueError(f"{path.name} is not a readable map file ({e})") from None
    except Exception:
        con.close()
        raise
    con.row_factory = sqlite3.Row
    return con


def _text(v, limit):
    return v if isinstance(v, str) and 0 < len(v) <= limit and "\0" not in v else None


def _num(v, lo=-MAX_COORD, hi=MAX_COORD):
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) and lo <= v <= hi else None


def _resref(v):
    return v.lower() if isinstance(v, str) and RESREF.match(v) else None


def clean_area(r):
    resref = _resref(r.get("resref"))
    if not resref:
        return None
    w, h = r.get("width"), r.get("height")
    size_ok = isinstance(w, int) and isinstance(h, int) and 1 <= w <= MAX_TILES and 1 <= h <= MAX_TILES
    return {"resref": resref, "name": _text(r.get("name"), 200), "tileset": _resref(r.get("tileset")),
            "width": w if size_ok else None, "height": h if size_ok else None,
            "server": _text(r.get("server"), 64), "first_seen": _num(r.get("first_seen"), 0, 4e9)}


def clean_poi(r):
    area, kind = _resref(r.get("area")), r.get("kind")
    x, y, z = _num(r.get("x")), _num(r.get("y")), _num(r.get("z"), -1000, 1000)
    if not area or kind not in ("pin", "door", "user") or x is None or y is None:
        return None
    return {"area": area, "kind": kind, "name": _text(r.get("name"), 200), "tag": _text(r.get("tag"), 64),
            "x": x, "y": y, "z": z or 0.0}


def clean_transition(r):
    out = {"from_area": _resref(r.get("from_area")), "to_area": _resref(r.get("to_area"))}
    for k in ("from_x", "from_y", "to_x", "to_y"):
        out[k] = _num(r.get(k))
    for k in ("from_z", "to_z"):
        out[k] = _num(r.get(k), -1000, 1000) or 0.0
    if None in (out["from_area"], out["to_area"], out["from_x"], out["from_y"], out["to_x"], out["to_y"]):
        return None
    out["from_server"], out["to_server"] = _text(r.get("from_server"), 64), _text(r.get("to_server"), 64)
    out["kind"] = r.get("kind") if r.get("kind") in ("walk", "portal") else "walk"
    out["confirmed"] = r.get("confirmed", 1) in (1, True)
    return out


def clean_tiles(r):
    """A tile layout: w*h entries of [tile_id, orientation 0-3, height]."""
    import json
    resref, tileset, w, h = _resref(r.get("resref")), _resref(r.get("tileset")), r.get("width"), r.get("height")
    if not (resref and tileset and isinstance(w, int) and isinstance(h, int)
            and 1 <= w <= MAX_TILES and 1 <= h <= MAX_TILES):
        return None
    raw = r.get("tiles")
    if not isinstance(raw, str) or len(raw) > w * h * 40 + 16:
        return None
    try:
        tiles = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(tiles, list) or len(tiles) != w * h:
        return None
    for t in tiles:
        if not (isinstance(t, list) and len(t) == 3 and all(isinstance(v, int) for v in t)
                and 0 <= t[0] <= 100_000 and 0 <= t[1] <= 3 and -100 <= t[2] <= 100):
            return None
    return {"resref": resref, "tileset": tileset, "width": w, "height": h, "tiles": tiles}


LEGACY_DATA = Path(__file__).resolve().parent.parent / "data"     # before release prep


def _db_mtime(p):
    """Last change to a database, counting its write-ahead log."""
    wal = p.with_name(p.name + "-wal")
    return max(p.stat().st_mtime, wal.stat().st_mtime if wal.exists() else 0)


def migrate_legacy(log=print):
    """One-time: copy data from earlier locations (<project>/data, %LOCALAPPDATA%\\NWN GPS) into
    DATA_DIR, taking the newest copy of each database. Copies, never moves: old folders are left as
    they were (rollback = delete DATA_DIR)."""
    import shutil
    from .config import OLD_LOCALAPPDATA_DIR
    sources = [d for d in (OLD_LOCALAPPDATA_DIR, LEGACY_DATA)
               if d.is_dir() and d.resolve() != DATA_DIR.resolve()]
    marker = DATA_DIR / ".migrated"
    if not sources or marker.exists():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    names = {p.name for d in sources for p in d.glob("*.sqlite")}
    for name in sorted(names):
        dest = DATA_DIR / name
        if dest.exists():
            continue
        src_path = max((d / name for d in sources if (d / name).exists()), key=_db_mtime)
        src = sqlite3.connect(src_path)               # reads through the WAL, so nothing is lost
        out = sqlite3.connect(dest)
        with out:
            src.backup(out)
        src.close()
        out.close()
        copied.append(f"{name} (from {src_path.parent})")
    for name in ("recent.json", "ui.json", "nav_target.json"):
        found = [d / name for d in sources if (d / name).exists()]
        if found and not (DATA_DIR / name).exists():
            shutil.copy2(max(found, key=lambda p: p.stat().st_mtime), DATA_DIR / name)
            copied.append(name)
    maps = [d / "maps" for d in sources if (d / "maps").is_dir()]
    if maps and not (DATA_DIR / "maps").exists():
        (DATA_DIR / "maps").mkdir()
        for m in maps:
            for f in m.glob("*.png"):
                if not (DATA_DIR / "maps" / f.name).exists():
                    shutil.copy2(f, DATA_DIR / "maps" / f.name)
        copied.append("maps/")
    marker.write_text("\n".join(str(s) for s in sources))
    if copied:
        log(f"copied your existing map data to {DATA_DIR}: {', '.join(copied)}")
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
    def export(self, dest, share=False):
        """Consistent copy of this database (safe while the recorder is writing).
        share=True strips when-you-played data (timestamps, visit counts) from the copy."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(dest)
        with out:
            self.db.backup(out)
        if share:
            with out:
                out.execute("UPDATE areas SET first_seen=NULL, last_seen=NULL, visits=0")
                out.execute("UPDATE pois SET first_seen=NULL, last_seen=NULL")
                out.execute("UPDATE transitions SET first_seen=NULL, last_seen=NULL")
                out.execute("UPDATE area_tiles SET seen=NULL")
            out.execute("VACUUM")             # don't leave the old values in free pages
        out.close()
        return dest

    def backup(self, tag="backup"):
        return self.export(DATA_DIR / "backups" / f"{self.path.stem}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")

    def merge(self, other_path):
        """Merge another player's database into this one. The file is untrusted: it's opened
        read-only in SQLite's defensive mode, integrity-checked, size- and row-limited, and every
        value is validated (bad rows are skipped and counted as "rejected"). Areas fill in missing
        details, POIs and transitions are de-duplicated by distance, tile layouts are added where we
        have none. Returns counts of what was added. (For a dry run, merge into an export() copy.)"""
        other = open_untrusted(other_path)
        added = {"areas": 0, "areas_updated": 0, "pois": 0, "transitions": 0, "transitions_seen_again": 0,
                 "tile_layouts": 0, "rejected": 0}
        try:
            tables = {r[0] for r in other.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for r in other.execute("SELECT * FROM areas LIMIT ?", (MAX_ROWS["areas"],)):
                r = clean_area(dict(r))
                if r is None:
                    added["rejected"] += 1
                    continue
                mine = self.area(r["resref"])
                if mine is None:
                    added["areas"] += 1
                elif any(mine[k] is None and r[k] is not None for k in ("name", "tileset", "width", "height")):
                    added["areas_updated"] += 1
                self.db.execute(
                    """INSERT INTO areas(resref,name,tileset,width,height,first_seen,last_seen,visits,server)
                       VALUES(?,?,?,?,?,?,?,0,?)
                       ON CONFLICT(resref) DO UPDATE SET
                         name=COALESCE(name,excluded.name), tileset=COALESCE(tileset,excluded.tileset),
                         width=COALESCE(width,excluded.width), height=COALESCE(height,excluded.height),
                         server=COALESCE(server,excluded.server),
                         first_seen=COALESCE(MIN(first_seen,excluded.first_seen),first_seen,excluded.first_seen)""",
                    (r["resref"], r["name"], r["tileset"], r["width"], r["height"],
                     r["first_seen"], r["first_seen"], r["server"]))
            before = self.stats()["pois"]
            for r in other.execute("SELECT * FROM pois LIMIT ?", (MAX_ROWS["pois"],)):
                r = clean_poi(dict(r))
                if r is None:
                    added["rejected"] += 1
                    continue
                self.upsert_poi(r["area"], r["kind"], r["name"], r["tag"], r["x"], r["y"], r["z"])
            added["pois"] = self.stats()["pois"] - before
            for r in other.execute("SELECT * FROM transitions LIMIT ?", (MAX_ROWS["transitions"],)):
                r = clean_transition(dict(r))
                if r is None:
                    added["rejected"] += 1
                    continue
                _, new = self.add_transition(r["from_area"], (r["from_x"], r["from_y"], r["from_z"]),
                                             r["to_area"], (r["to_x"], r["to_y"], r["to_z"]),
                                             r["from_server"], r["to_server"], r["kind"], r["confirmed"])
                added["transitions" if new else "transitions_seen_again"] += 1
            if "area_tiles" in tables:
                for r in other.execute("SELECT resref, tileset, width, height, tiles FROM area_tiles LIMIT ?",
                                       (MAX_ROWS["area_tiles"],)):
                    t = clean_tiles(dict(r))
                    if t is None:
                        added["rejected"] += 1
                        continue
                    if not self.db.execute("SELECT 1 FROM area_tiles WHERE resref=?", (t["resref"],)).fetchone():
                        self.save_tiles(t["resref"], t["tileset"], t["width"], t["height"], t["tiles"])
                        added["tile_layouts"] += 1
            self.db.commit()
        finally:
            other.close()
        return added

    def stats(self):
        q = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {"areas": q("areas"), "pois": q("pois"), "transitions": q("transitions")}
