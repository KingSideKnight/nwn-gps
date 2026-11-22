"""SQLite storage for areas, points of interest and transitions.

Database file: <project>/data/<module>.sqlite (git-ignored; back it up by copying the file).
"""
import math
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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
"""

POI_MERGE_DIST = 2.0      # metres: same kind+name closer than this = same POI
TRANS_MERGE_DIST = 5.0    # metres: same from/to areas with exits this close = same transition
VIA_MAX_DIST = 6.0        # metres: a pin/door this close to an exit labels the transition


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


class Store:
    def __init__(self, module="arelith", path=None):
        DATA_DIR.mkdir(exist_ok=True)
        self.path = Path(path) if path else DATA_DIR / f"{module.lower()}.sqlite"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.commit()
        self.db.close()

    # --- writes -------------------------------------------------------------
    def upsert_area(self, resref, name, tileset=None, width=None, height=None, visit=False):
        now = time.time()
        self.db.execute(
            """INSERT INTO areas(resref,name,tileset,width,height,first_seen,last_seen,visits)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(resref) DO UPDATE SET
                 name=COALESCE(excluded.name,name), tileset=COALESCE(excluded.tileset,tileset),
                 width=COALESCE(excluded.width,width), height=COALESCE(excluded.height,height),
                 last_seen=excluded.last_seen, visits=visits+?""",
            (resref, name, tileset, width, height, now, now, int(visit), int(visit)))
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

    def add_transition(self, from_area, fpos, to_area, tpos):
        now = time.time()
        for r in self.db.execute("SELECT * FROM transitions WHERE from_area=? AND to_area=?", (from_area, to_area)):
            if dist(r["from_x"], r["from_y"], fpos[0], fpos[1]) < TRANS_MERGE_DIST:
                self.db.execute("UPDATE transitions SET count=count+1,last_seen=? WHERE id=?", (now, r["id"]))
                self.db.commit()
                return r["id"], False
        via = self.nearest_poi(from_area, fpos[0], fpos[1])
        cur = self.db.execute(
            """INSERT INTO transitions(from_area,from_x,from_y,from_z,to_area,to_x,to_y,to_z,via_poi,first_seen,last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (from_area, *fpos, to_area, *tpos, via["id"] if via else None, now, now))
        self.db.commit()
        return cur.lastrowid, True

    def commit(self):
        self.db.commit()

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

    def transitions(self):
        return self.db.execute("SELECT * FROM transitions").fetchall()

    def poi(self, pid):
        return self.db.execute("SELECT * FROM pois WHERE id=?", (pid,)).fetchone()

    def stats(self):
        q = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {"areas": q("areas"), "pois": q("pois"), "transitions": q("transitions")}
