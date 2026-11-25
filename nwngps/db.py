"""SQLite storage for areas, points of interest and transitions.

Database file: <project>/data/<module>.sqlite (git-ignored; back it up by copying the file).
"""
import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from pathlib import Path

from . import edges as E
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
-- What the GPS noticed the server changed (and undid on its own), so it can be listed and undone.
CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY,
    t           REAL,
    area        TEXT,
    what        TEXT,       -- layout | poi_retired | poi_back | link_stale | link_back
    ref         INTEGER,    -- pois.id / transitions.id (NULL for layout)
    note        TEXT,
    data        TEXT,       -- layout: the previous area_tiles row as JSON
    undone      REAL
);
-- Which server ("world") this map belongs to, so a friend's file can't merge into another server's map.
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
-- Friends' map files merged into this one (each can be undone; the same file is never merged twice).
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    t           REAL,
    file        TEXT,
    sha256      TEXT,
    source      TEXT,       -- the map it came from (its random map id), see Store.merge
    added       TEXT,       -- JSON counts shown to the player
    undone      REAL
);
-- Which map has vouched for which link: each map counts once per link, however often it's imported.
CREATE TABLE IF NOT EXISTS sightings (
    tid         INTEGER,
    source      TEXT,
    import_id   INTEGER,
    prev_kind   TEXT,       -- the link before this import touched it (for undo)
    prev_confirmed INTEGER,
    PRIMARY KEY (tid, source)
);
"""

# Columns added after the first schema; applied with ALTER TABLE when missing.
# import_id: the import (imports.id) that added the row; cleared once you see it yourself in game.
MIGRATIONS = {
    "areas": {"server": "TEXT", "import_id": "INTEGER"},
    "pois": {"missed": "INTEGER DEFAULT 0",            # visits in a row it wasn't there
             "retired": "REAL",                        # when it was hidden as gone (NULL = current)
             "import_id": "INTEGER"},
    "transitions": {"from_server": "TEXT", "to_server": "TEXT",
                    "kind": "TEXT DEFAULT 'walk'",       # walk | portal | jump | death | respawn (edges.py)
                    "confirmed": "INTEGER DEFAULT 1",    # 0 = not routed yet (see edges.py)
                    "stale": "REAL",                     # when it stopped being trusted (NULL = fine)
                    "import_id": "INTEGER"},
    "area_tiles": {"import_id": "INTEGER"},
}
SOURCE_ID = re.compile(r"^[0-9a-f]{16}$")

# Map changes (see Store.end_visit). Nothing is ever deleted: retired / stale rows are hidden and
# come back by themselves when seen again (or with `nwngps changes` / `restore`).
RETIRE_AFTER = 3          # visits in a row without a pin / door before it is hidden as gone
GOOD_SCAN = 0.5           # a visit only counts if it saw at least this share of the nearby known ones
PASSED_NEAR = 15.0        # metres: the game only loads doors near you (an area's count varies 33-47
                          # as you walk), so something counts as missed only if a scan ran this close
SAME_DOOR = 1.5           # metres: two links starting this close (or at the same door) share an exit


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


EXPORT_NAME = re.compile(r"nwn-gps-(\w{1,100})-\d{4}-\d{2}-\d{2}_\d{4}")


class AlreadyImported(ValueError):
    """This exact file was merged before (and not undone)."""


class OtherWorld(ValueError):
    """A friend's map file belongs to another server than the map it would merge into."""

    def __init__(self, name, world):
        self.world = world
        super().__init__(f"{name} is a map of another server ({world})")


def file_world(con, path):
    """Server a map file belongs to (db_name form), from its meta tag or, for files exported by
    NWN GPS 0.1.4 and older (no tag), from the export file name. None if it can't tell."""
    try:
        kind = con.execute("SELECT type FROM sqlite_master WHERE name='meta'").fetchone()
        if kind and kind[0] == "table":
            r = con.execute("SELECT value FROM meta WHERE key='world' LIMIT 1").fetchone()
            if r and isinstance(r[0], str) and re.fullmatch(r"\w{1,100}", r[0]):
                return r[0].lower()
    except sqlite3.DatabaseError:
        pass
    m = EXPORT_NAME.fullmatch(Path(path).stem)
    return m.group(1).lower() if m else None


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_source(con):
    """The random map id a file carries (NWN GPS 0.1.6+), or None."""
    try:
        kind = con.execute("SELECT type FROM sqlite_master WHERE name='meta'").fetchone()
        if kind and kind[0] == "table":
            r = con.execute("SELECT value FROM meta WHERE key='source' LIMIT 1").fetchone()
            if r and isinstance(r[0], str) and SOURCE_ID.match(r[0]):
                return r[0]
    except sqlite3.DatabaseError:
        pass
    return None


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
    out["kind"] = r.get("kind") if r.get("kind") in E.KINDS else "walk"
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
        if path is None and self.world != "unknown":       # a world's own map: tag it (exports copy the tag)
            self.db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('world', ?)", (db_name(self.world),))
            # A random id for this map (nothing about you in it): lets a friend count your map once
            # per link however many of your exports they import.
            self.db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('source', ?)", (secrets.token_hex(8),))
        self.db.commit()
        self._hold = False            # True while merging: one commit (or rollback) for the whole file

    def _commit(self):
        if not self._hold:
            self.db.commit()

    def my_source(self):
        r = self.db.execute("SELECT value FROM meta WHERE key='source'").fetchone()
        return r[0] if r else None

    def my_world(self):
        """The server this map belongs to (db_name form), or None if unknown."""
        r = self.db.execute("SELECT value FROM meta WHERE key='world'").fetchone()
        if r and r[0]:
            return r[0]
        return db_name(self.world) if self.world != "unknown" else None

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
                 last_seen=excluded.last_seen, visits=visits+?, import_id=NULL""",
            (resref, name, tileset, width, height, now, now, int(visit), server, int(visit)))
        self._commit()

    def upsert_poi(self, area, kind, name, tag, x, y, z, live=True, import_id=None):
        """live=False (merging someone else's map): an existing match is left exactly as it is, so
        an old copy can't bring back a pin / door you've seen the server remove."""
        now = time.time()
        for r in self.db.execute("SELECT id,x,y,retired FROM pois WHERE area=? AND kind=? AND name IS ? AND tag IS ?",
                                 (area, kind, name, tag)).fetchall():
            if dist(r["x"], r["y"], x, y) < POI_MERGE_DIST:
                if live:
                    self.db.execute("UPDATE pois SET last_seen=?, missed=0, retired=NULL, import_id=NULL WHERE id=?",
                                    (now, r["id"]))
                    if r["retired"] is not None:
                        self.log_change(area, "poi_back", r["id"], f"{kind} {name or ''} is back")
                return r["id"]
        cur = self.db.execute(
            "INSERT INTO pois(area,kind,name,tag,x,y,z,first_seen,last_seen,import_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (area, kind, name, tag, x, y, z, now, now, import_id))
        return cur.lastrowid

    def log_change(self, area, what, ref=None, note="", data=None):
        self.db.execute("INSERT INTO changes(t,area,what,ref,note,data) VALUES(?,?,?,?,?,?)",
                        (time.time(), area, what, ref, note, data))

    def nearest_poi(self, area, x, y, max_dist=VIA_MAX_DIST):
        best = None
        for r in self.db.execute("SELECT * FROM pois WHERE area=? AND kind IN ('pin','door') AND retired IS NULL",
                                 (area,)):
            d = dist(r["x"], r["y"], x, y)
            # prefer pins (Arelith marks transitions with them) when distances are similar
            score = d - (1.0 if r["kind"] == "pin" else 0.0)
            if d <= max_dist and (best is None or score < best[0]):
                best = (score, r)
        return best[1] if best else None

    def add_transition(self, from_area, fpos, to_area, tpos, from_server=None, to_server=None,
                       kind="walk", confirmed=True, live=True, source=None, import_id=None):
        """Record (or re-confirm) an edge. Seeing it again confirms it, except: a jump needs
        edges.JUMP_CONFIRM sightings, and a death edge is never confirmed. A jump seen again as a
        normal walk/portal (a door turned up there) becomes that kind. Walking a stale link again
        (live) makes it trusted again; a new link out of the same door makes older ones to other
        places stale (the server re-pointed the door). live=False: merging someone else's map
        (`source`, the map it came from, counts once per link; None = it can't count at all)."""
        now = time.time()
        for r in self.db.execute("SELECT * FROM transitions WHERE from_area=? AND to_area=?",
                                 (from_area, to_area)).fetchall():
            if dist(r["from_x"], r["from_y"], fpos[0], fpos[1]) < TRANS_MERGE_DIST:
                if not live and r["stale"] is not None:
                    return r["id"], False
                if not live:
                    if source is None or self.db.execute("SELECT 1 FROM sightings WHERE tid=? AND source=?",
                                                         (r["id"], source)).fetchone():
                        return r["id"], False          # that map has vouched for this link already
                    self.db.execute("INSERT INTO sightings(tid,source,import_id,prev_kind,prev_confirmed) "
                                    "VALUES(?,?,?,?,?)", (r["id"], source, import_id, r["kind"], r["confirmed"]))
                if r["stale"] is not None:
                    self.db.execute("UPDATE transitions SET stale=NULL WHERE id=?", (r["id"],))
                    self.log_change(from_area, "link_back", r["id"], "walked again: trusted again")
                old = r["kind"] or "walk"
                new_kind = kind if (old == "jump" and kind in E.REVERSIBLE) else old
                if new_kind in E.NEVER_ROUTED:
                    ok = 0
                elif new_kind == "jump":
                    ok = int(bool(r["confirmed"]) or (r["count"] or 1) + 1 >= E.JUMP_CONFIRM or bool(confirmed))
                else:
                    ok = 1
                self.db.execute("UPDATE transitions SET count=count+1, confirmed=?, kind=? WHERE id=?",
                                (ok, new_kind, r["id"]))
                if live:      # where you arrive is where you arrive now (the far side may have moved)
                    # (last_seen is only ever your own play: undoing an import relies on that)
                    self.db.execute("UPDATE transitions SET to_x=?, to_y=?, to_z=?, last_seen=?, import_id=NULL "
                                    "WHERE id=?", (*tpos, now, r["id"]))
                if live and new_kind in E.REVERSIBLE:
                    self._supersede(r["id"], from_area, fpos, to_area)
                self._commit()
                return r["id"], False
        if not live and source is None:
            source = "unknown"
        via = self.nearest_poi(from_area, fpos[0], fpos[1])
        cur = self.db.execute(
            """INSERT INTO transitions(from_area,from_x,from_y,from_z,to_area,to_x,to_y,to_z,via_poi,first_seen,last_seen,
                                       from_server,to_server,kind,confirmed,import_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (from_area, *fpos, to_area, *tpos, via["id"] if via else None, now, now if live else None,
             from_server, to_server, kind, int(confirmed), import_id))
        if not live:
            self.db.execute("INSERT INTO sightings(tid,source,import_id) VALUES(?,?,?)",
                            (cur.lastrowid, source, import_id))
        if kind in E.REVERSIBLE and live:
            self._supersede(cur.lastrowid, from_area, fpos, to_area)
        elif kind in E.REVERSIBLE and self._exit_taken(cur.lastrowid, from_area, fpos, to_area):
            # someone else's link out of a door that (for you) leads elsewhere: yours wins
            self.mark_stale(cur.lastrowid, from_area, "imported; that exit leads elsewhere in your map")
        self._commit()
        return cur.lastrowid, True

    def _same_exit(self, tid, from_area, fpos, to_area):
        """Trusted walk / portal links leaving from the same spot as `fpos` to another area.
        By distance only: one map pin often labels two neighbouring doors."""
        return [r for r in self.db.execute("SELECT * FROM transitions WHERE from_area=? AND to_area!=? "
                                           "AND stale IS NULL AND kind IN ('walk','portal') AND id!=?",
                                           (from_area, to_area, tid)).fetchall()
                if dist(r["from_x"], r["from_y"], fpos[0], fpos[1]) < SAME_DOOR]

    def _exit_taken(self, tid, from_area, fpos, to_area):
        return bool(self._same_exit(tid, from_area, fpos, to_area))

    def _supersede(self, tid, from_area, fpos, to_area):
        """The exit you just used now leads to `to_area`: older links out of the same door to
        somewhere else stop being trusted."""
        for r in self._same_exit(tid, from_area, fpos, to_area):
            self.mark_stale(r["id"], from_area, f"same exit now leads to {self.area_name(to_area)}")

    def mark_stale(self, tid, area, why):
        self.db.execute("UPDATE transitions SET stale=? WHERE id=?", (time.time(), tid))
        self.log_change(area, "link_stale", tid, why)

    def end_visit(self, area, seen_ids, path, kinds=("pin", "door"), size=None):
        """After a visit: pins / doors of `kinds` that a scan ran within PASSED_NEAR of (path:
        your position at each scan) but that weren't there are counted as missed, and hidden once missed
        RETIRE_AFTER visits in a row. Then links out of the area that no longer start at a door,
        pin or map edge stop being trusted. Visits that saw too little of what we know nearby
        (still loading, a bad read) count for nothing. Returns {"retired": [...], "stale": [...]}
        or None if the visit didn't count."""
        out = {"retired": [], "stale": []}
        if not kinds or not path:
            return out
        ph = ",".join("?" * len(kinds))
        known = [r for r in self.db.execute(f"SELECT id, kind, name, missed, x, y FROM pois WHERE area=? "
                                            f"AND kind IN ({ph}) AND retired IS NULL", (area, *kinds)).fetchall()
                 if any(dist(r["x"], r["y"], px, py) <= PASSED_NEAR for px, py in path)]
        seen = set(seen_ids)
        if not known:
            return out
        if not seen or sum(r["id"] in seen for r in known) < GOOD_SCAN * len(known):
            return None
        now = time.time()
        for r in known:
            if r["id"] in seen:
                if r["missed"]:
                    self.db.execute("UPDATE pois SET missed=0 WHERE id=?", (r["id"],))
                continue
            missed = (r["missed"] or 0) + 1
            if missed >= RETIRE_AFTER:
                self.db.execute("UPDATE pois SET missed=?, retired=? WHERE id=?", (missed, now, r["id"]))
                self.log_change(area, "poi_retired", r["id"],
                                f"{r['kind']} {r['name'] or ''} not seen {missed} visits in a row")
                out["retired"].append(r["id"])
            else:
                self.db.execute("UPDATE pois SET missed=? WHERE id=?", (missed, r["id"]))
        if out["retired"]:
            out["stale"] = self.check_links(area, size)
        self.db.commit()
        return out

    def check_links(self, area, size=None):
        """Walk / portal links out of `area` whose start has no door, pin or map edge any more.
        If the area's size is unknown (no edge test possible), only links whose own door / pin
        was retired are touched."""
        out = []
        if not size:
            a = self.area(area)
            size = (a["width"], a["height"]) if a and a["width"] and a["height"] else None
        for r in self.db.execute("SELECT t.*, p.retired AS via_retired FROM transitions t "
                                 "LEFT JOIN pois p ON p.id=t.via_poi WHERE t.from_area=? AND t.stale IS NULL "
                                 "AND t.kind IN ('walk','portal')", (area,)).fetchall():
            if size is None and r["via_retired"] is None:
                continue
            via = self.nearest_poi(area, r["from_x"], r["from_y"], max_dist=E.DOOR_NEAR)
            d = dist(via["x"], via["y"], r["from_x"], r["from_y"]) if via else None
            if not E.natural_exit(r["from_x"], r["from_y"], size, d):
                self.mark_stale(r["id"], area, "its door / pin is gone")
                out.append(r["id"])
        return out

    def check_layout(self, resref, tileset, w, h, tiles):
        """Compare a freshly read tile layout with the saved one. Saves it if there was none;
        if it differs, backs up the database, keeps the old layout in `changes` and saves the
        new one. Returns None (no change), "new" or "changed"."""
        import json
        old = self.db.execute("SELECT * FROM area_tiles WHERE resref=?", (resref,)).fetchone()
        if old is None:
            self.save_tiles(resref, tileset, w, h, tiles)
            return "new"
        if (old["tileset"], old["width"], old["height"]) == (tileset, w, h) and \
                [list(t) for t in json.loads(old["tiles"])] == [list(t) for t in tiles]:
            return None
        self.backup("before-layout")
        self.log_change(resref, "layout", None,
                        f"layout changed ({old['width']}x{old['height']} {old['tileset']} -> {w}x{h} {tileset})",
                        json.dumps({k: old[k] for k in ("tileset", "width", "height", "tiles")}))
        self.save_tiles(resref, tileset, w, h, tiles)
        return "changed"

    def changes(self, area=None, limit=50):
        q = ("SELECT c.*, a.name AS area_name FROM changes c LEFT JOIN areas a ON a.resref=c.area"
             + (" WHERE c.area=?" if area else "") + " ORDER BY c.id DESC LIMIT ?")
        return self.db.execute(q, ((area, limit) if area else (limit,))).fetchall()

    def restore(self, change_id):
        """Undo one change the GPS made by itself. Returns a description, or None if there's
        nothing to undo (unknown id, already undone, or a 'back' entry)."""
        import json
        c = self.db.execute("SELECT * FROM changes WHERE id=?", (change_id,)).fetchone()
        if not c or c["undone"] is not None or c["what"] not in ("layout", "poi_retired", "link_stale"):
            return None
        self.backup("before-restore")
        if c["what"] == "layout":
            old = json.loads(c["data"])
            self.save_tiles(c["area"], old["tileset"], old["width"], old["height"], json.loads(old["tiles"]))
        elif c["what"] == "poi_retired":
            self.db.execute("UPDATE pois SET retired=NULL, missed=0 WHERE id=?", (c["ref"],))
        else:
            self.db.execute("UPDATE transitions SET stale=NULL WHERE id=?", (c["ref"],))
        self.db.execute("UPDATE changes SET undone=? WHERE id=?", (time.time(), change_id))
        self.db.commit()
        return c["note"]

    def links_version(self):
        """Changes whenever links are added, walked again, or stop / start being trusted."""
        return tuple(self.db.execute("SELECT COUNT(*), MAX(last_seen), MAX(stale), SUM(stale IS NULL), "
                                     "SUM(confirmed), SUM(count), MAX(id) FROM transitions").fetchone())

    def promote_jumps(self, area):
        """Unconfirmed jumps out of `area` that turn out to start at a door / pin we know now
        (the area's doors may only be recorded after you've left it once) become walk/portal."""
        out = []
        for r in self.db.execute("SELECT * FROM transitions WHERE from_area=? AND kind='jump' AND confirmed=0",
                                 (area,)).fetchall():
            via = self.nearest_poi(area, r["from_x"], r["from_y"], max_dist=E.DOOR_NEAR)
            if via:
                kind = "walk" if r["from_server"] == r["to_server"] else "portal"
                self.db.execute("UPDATE transitions SET kind=?, confirmed=1, via_poi=? WHERE id=?",
                                (kind, via["id"], r["id"]))
                out.append(r["id"])
        if out:
            self.db.commit()
        return out

    def links(self, area=None):
        """Transitions with area names, for reviewing / fixing what was recorded."""
        q = ("SELECT t.*, fa.name AS from_name, ta.name AS to_name FROM transitions t "
             "LEFT JOIN areas fa ON fa.resref=t.from_area LEFT JOIN areas ta ON ta.resref=t.to_area")
        if area:
            return self.db.execute(q + " WHERE t.from_area=? OR t.to_area=? ORDER BY t.id", (area, area)).fetchall()
        return self.db.execute(q + " ORDER BY t.id").fetchall()

    def set_link(self, tid, confirmed=None, kind=None):
        """Trust (or distrust) a recorded link by hand. Returns False if there is no such link."""
        r = self.db.execute("SELECT id FROM transitions WHERE id=?", (tid,)).fetchone()
        if not r:
            return False
        if kind is not None:
            if kind not in E.KINDS:
                raise ValueError(f"kind must be one of {E.KINDS}")
            self.db.execute("UPDATE transitions SET kind=? WHERE id=?", (kind, tid))
        if confirmed is not None:
            self.db.execute("UPDATE transitions SET confirmed=? WHERE id=?", (int(bool(confirmed)), tid))
            if confirmed:                 # trusting it by hand also overrides "the map changed"
                self.db.execute("UPDATE transitions SET stale=NULL WHERE id=?", (tid,))
        self.db.execute("UPDATE transitions SET import_id=NULL WHERE id=?", (tid,))   # yours now: undo keeps it
        self.db.commit()
        return True

    def forget_link(self, tid):
        """Delete one recorded link (after a backup). Returns the backup path, or None if no such link."""
        if not self.db.execute("SELECT id FROM transitions WHERE id=?", (tid,)).fetchone():
            return None
        bak = self.backup("before-forget")
        self.db.execute("DELETE FROM transitions WHERE id=?", (tid,))
        self.db.commit()
        return bak

    def commit(self):
        self.db.commit()

    def save_tiles(self, resref, tileset, w, h, tiles, import_id=None):
        self.db.execute("INSERT OR REPLACE INTO area_tiles(resref,tileset,width,height,tiles,seen,import_id) "
                        "VALUES(?,?,?,?,?,?,?)", (resref, tileset, w, h, json.dumps(tiles), time.time(), import_id))
        self._commit()

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
            "WHERE (p.name LIKE ? OR p.tag LIKE ?) AND p.name NOT IN ('Door','Window') AND p.retired IS NULL "
            "LIMIT ?", (like, like, limit)).fetchall()
        return list(areas) + list(pois)

    def area_pois(self, area):
        """Current (not retired) pins, doors and your own markers in an area, for drawing."""
        return self.db.execute("SELECT kind,name,x,y FROM pois WHERE area=? AND retired IS NULL", (area,)).fetchall()

    def pois_version(self, area):
        """Changes when a pin / door is added, retired or comes back (the recorder is another process)."""
        return (area, *self.db.execute("SELECT SUM(retired IS NULL), MAX(CASE WHEN retired IS NULL THEN id END), "
                                       "MAX(retired), COUNT(*) FROM pois WHERE area=?", (area,)).fetchone())

    def transitions(self, include_unconfirmed=False, include_stale=False):
        where = [w for w, on in (("confirmed=1", not include_unconfirmed), ("stale IS NULL", not include_stale)) if on]
        q = "SELECT * FROM transitions" + (" WHERE " + " AND ".join(where) if where else "")
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
                out.execute("DELETE FROM changes")              # your own play history
                out.execute("DELETE FROM imports")              # whose maps you merged
                out.execute("DELETE FROM sightings")
                for table in ("areas", "pois", "transitions", "area_tiles"):
                    out.execute(f"UPDATE {table} SET import_id=NULL")
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
        have none. Returns counts of what was added. (For a dry run, merge into an export() copy.)
        Raises OtherWorld, merging nothing, if the file is tagged as another server's map, and
        AlreadyImported if this exact file was merged before (and that import wasn't undone).

        All or nothing: the whole file is one transaction. Everything it adds is labelled with the
        import, so `undo_import` can take it out again later. Each map (its random `source` id; for
        older files without one, the file itself) counts as one sighting per link, however many of
        its exports you import, so re-imports can't make an untrusted teleport routable."""
        other = open_untrusted(other_path)
        added = {"areas": 0, "areas_updated": 0, "pois": 0, "transitions": 0, "transitions_seen_again": 0,
                 "tile_layouts": 0, "gone_skipped": 0, "rejected": 0}
        try:
            name = Path(other_path).name
            theirs, mine = file_world(other, other_path), self.my_world()
            if theirs and mine and theirs != mine.lower():
                raise OtherWorld(name, theirs)
            sha = file_sha256(other_path)
            prev = self.db.execute("SELECT id, t FROM imports WHERE sha256=? AND undone IS NULL", (sha,)).fetchone()
            if prev:
                raise AlreadyImported(f"{name} was already imported on {time.strftime('%Y-%m-%d', time.localtime(prev['t']))}")
            source = file_source(other) or f"file-{sha[:16]}"
            if source == self.my_source():
                source = None                 # your own map coming back: adds what's missing, vouches for nothing
            self._hold = True
            iid = self.db.execute("INSERT INTO imports(t, file, sha256, source) VALUES(?,?,?,?)",
                                  (time.time(), name[:200], sha, source)).lastrowid
            self._merge_rows(other, added, iid, source)
            self.db.execute("UPDATE imports SET added=? WHERE id=?", (json.dumps(added), iid))
            self.db.commit()
            added["import_id"] = iid
        except BaseException:
            if self._hold:
                self.db.rollback()
            raise
        finally:
            self._hold = False
            other.close()
        return added

    def _merge_rows(self, other, added, iid, source):
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
                """INSERT INTO areas(resref,name,tileset,width,height,first_seen,last_seen,visits,server,import_id)
                   VALUES(?,?,?,?,?,?,?,0,?,?)
                   ON CONFLICT(resref) DO UPDATE SET
                     name=COALESCE(name,excluded.name), tileset=COALESCE(tileset,excluded.tileset),
                     width=COALESCE(width,excluded.width), height=COALESCE(height,excluded.height),
                     server=COALESCE(server,excluded.server),
                     first_seen=COALESCE(MIN(first_seen,excluded.first_seen),first_seen,excluded.first_seen)""",
                (r["resref"], r["name"], r["tileset"], r["width"], r["height"],
                 r["first_seen"], r["first_seen"], r["server"], iid))
        before = self.stats()["pois"]
        # Their pins / doors / links the server has since removed (retired / stale in their copy)
        # are skipped, and nothing of theirs brings back one you've seen go (live=False).
        for r in other.execute("SELECT * FROM pois LIMIT ?", (MAX_ROWS["pois"],)):
            if r.keys().count("retired") and r["retired"] is not None:
                added["gone_skipped"] += 1
                continue
            r = clean_poi(dict(r))
            if r is None:
                added["rejected"] += 1
                continue
            self.upsert_poi(r["area"], r["kind"], r["name"], r["tag"], r["x"], r["y"], r["z"], live=False,
                            import_id=iid)
        added["pois"] = self.stats()["pois"] - before
        for r in other.execute("SELECT * FROM transitions LIMIT ?", (MAX_ROWS["transitions"],)):
            if r.keys().count("stale") and r["stale"] is not None:
                added["gone_skipped"] += 1
                continue
            r = clean_transition(dict(r))
            if r is None:
                added["rejected"] += 1
                continue
            _, new = self.add_transition(r["from_area"], (r["from_x"], r["from_y"], r["from_z"]),
                                         r["to_area"], (r["to_x"], r["to_y"], r["to_z"]),
                                         r["from_server"], r["to_server"], r["kind"], r["confirmed"],
                                         live=False, source=source, import_id=iid)
            added["transitions" if new else "transitions_seen_again"] += 1
        if "area_tiles" in tables:
            for r in other.execute("SELECT resref, tileset, width, height, tiles FROM area_tiles LIMIT ?",
                                   (MAX_ROWS["area_tiles"],)):
                t = clean_tiles(dict(r))
                if t is None:
                    added["rejected"] += 1
                    continue
                if not self.db.execute("SELECT 1 FROM area_tiles WHERE resref=?", (t["resref"],)).fetchone():
                    self.save_tiles(t["resref"], t["tileset"], t["width"], t["height"], t["tiles"], import_id=iid)
                    added["tile_layouts"] += 1

    def imports(self):
        """Merged map files, newest first."""
        return self.db.execute("SELECT * FROM imports ORDER BY id DESC").fetchall()

    def undo_import(self, iid):
        """Take one imported file back out of your map (your map is backed up first). Removes what
        it added, unless you've since seen it yourself in game, and takes back the sightings it
        counted (links it made trusted go back to untrusted). Area details it filled into areas you
        already had stay. Returns a summary dict, or None if there's no such import / it's undone."""
        imp = self.db.execute("SELECT * FROM imports WHERE id=? AND undone IS NULL", (iid,)).fetchone()
        if not imp:
            return None
        backup = self.backup("before-undo-import")
        out = {"file": imp["file"], "backup": str(backup), "areas": 0, "pois": 0, "transitions": 0,
               "tile_layouts": 0, "links_untrusted": 0}
        self._hold = True
        try:
            q = self.db.execute
            for s in q("SELECT s.*, t.import_id AS row_import, t.last_seen, t.kind, t.confirmed, t.count "
                       "FROM sightings s JOIN transitions t ON t.id=s.tid WHERE s.import_id=?", (iid,)).fetchall():
                if s["row_import"] == iid:
                    continue                      # the link itself goes below
                q("UPDATE transitions SET count=MAX(1, count-1) WHERE id=?", (s["tid"],))
                # put it back as it was, unless you've walked it yourself since the import
                if (s["last_seen"] is None or s["last_seen"] <= imp["t"]) and s["prev_kind"] is not None:
                    if s["confirmed"] and not s["prev_confirmed"]:
                        out["links_untrusted"] += 1
                    q("UPDATE transitions SET kind=?, confirmed=? WHERE id=?",
                      (s["prev_kind"], s["prev_confirmed"], s["tid"]))
            q("DELETE FROM sightings WHERE import_id=?", (iid,))
            gone = [r[0] for r in q("SELECT id FROM transitions WHERE import_id=?", (iid,))]
            for tid in gone:
                q("DELETE FROM sightings WHERE tid=?", (tid,))
                q("DELETE FROM changes WHERE ref=? AND what IN ('link_stale','link_back')", (tid,))
            out["transitions"] = q("DELETE FROM transitions WHERE import_id=?", (iid,)).rowcount
            q("UPDATE transitions SET via_poi=NULL WHERE via_poi IN (SELECT id FROM pois WHERE import_id=?)", (iid,))
            out["pois"] = q("DELETE FROM pois WHERE import_id=?", (iid,)).rowcount
            out["tile_layouts"] = q("DELETE FROM area_tiles WHERE import_id=?", (iid,)).rowcount
            # an area it added stays if something else still lives in it (another import, your own play)
            out["areas"] = q("""DELETE FROM areas WHERE import_id=? AND
                                  resref NOT IN (SELECT area FROM pois) AND
                                  resref NOT IN (SELECT from_area FROM transitions) AND
                                  resref NOT IN (SELECT to_area FROM transitions) AND
                                  resref NOT IN (SELECT resref FROM area_tiles)""", (iid,)).rowcount
            q("UPDATE areas SET import_id=NULL WHERE import_id=?", (iid,))
            q("UPDATE imports SET undone=? WHERE id=?", (time.time(), iid))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._hold = False
        return out

    def stats(self):
        q = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {"areas": q("areas"), "pois": q("pois"), "transitions": q("transitions")}
