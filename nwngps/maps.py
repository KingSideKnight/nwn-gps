"""Area maps from real tile art.

read_tiles(mem, area_ptr, w, h)      -> [(tile_id, orientation, height), ...] row-major from the SW corner
Maps(resources).image(tileset, w, h, tiles) -> PIL image (north up), cached in data/maps/

Each tile's minimap picture is the tileset's ImageMap2D texture (e.g. mi_tno01_a01_01.tga),
rotated by the tile's orientation.
"""
import hashlib
import io
import json
import re
import struct

from PIL import Image

from . import layout as L
from .db import DATA_DIR

MAP_DIR = DATA_DIR / "maps"
TILE_PX = 32


def read_tiles(mem, area, w, h):
    base = mem.u64(area + L.AREA_TILES)
    if not base or not w or not h or w * h > 64 * 64:
        return None
    raw = mem.read(base, w * h * L.TILE_STRIDE)
    if not raw or len(raw) < w * h * L.TILE_STRIDE:
        return None
    tiles = []
    for i in range(w * h):
        o = i * L.TILE_STRIDE
        tid, height, x, y, orient = struct.unpack_from("<iiiii", raw, o + L.TILE_ID)
        if (x, y) != (i % w, i // w):
            return None            # not (or no longer) a valid tile array
        tiles.append((tid, orient & 3, height))
    return tiles


def parse_set(text):
    """{tile_id: ImageMap2D resref} from a tileset .set file."""
    out = {}
    for m in re.finditer(r"^\[TILE(\d+)\]\s*$(.*?)(?=^\[)", text, re.S | re.M):
        img = re.search(r"^ImageMap2D=(\S+)", m.group(2), re.M)
        if img:
            out[int(m.group(1))] = img.group(1).lower()
    return out


class Maps:
    def __init__(self, resources):
        self.res = resources
        self.sets = {}
        self.textures = {}
        MAP_DIR.mkdir(parents=True, exist_ok=True)

    def is_interior(self, name):
        """The tileset's [GENERAL] Interior flag (buildings, dungeons) - None if unknown."""
        key = ("interior", name)
        if key not in self.sets:
            data = self.res.get(name, "set") if name else None
            m = re.search(rb"^Interior=(\d)", data or b"", re.M)
            self.sets[key] = (m.group(1) == b"1") if m else None
        return self.sets[key]

    def tileset(self, name):
        if name not in self.sets:
            data = self.res.get(name, "set")
            self.sets[name] = parse_set(data.decode("latin-1")) if data else {}
        return self.sets[name]

    def texture(self, resref):
        if resref not in self.textures:
            img = None
            for ext in ("tga", "dds", "png"):
                data = self.res.get(resref, ext)
                if data:
                    try:
                        img = Image.open(io.BytesIO(data)).convert("RGBA").resize((TILE_PX, TILE_PX), Image.LANCZOS)
                        break
                    except OSError:
                        continue
            self.textures[resref] = img
        return self.textures[resref]

    @staticmethod
    def key(tileset, w, h, tiles):
        return hashlib.sha1(json.dumps([tileset, w, h, tiles]).encode()).hexdigest()[:16]

    def image(self, tileset, w, h, tiles):
        """North-up RGBA map of the area (w*32 x h*32), cached on disk by content."""
        path = MAP_DIR / f"{self.key(tileset, w, h, tiles)}.png"
        if path.exists():
            return Image.open(path).convert("RGBA")
        ids = self.tileset(tileset)
        img = Image.new("RGBA", (w * TILE_PX, h * TILE_PX), (0, 0, 0, 0))
        missing = 0
        for i, (tid, orient, _height) in enumerate(tiles):
            tex = self.texture(ids[tid]) if tid in ids else None
            if tex is None:
                missing += 1
                continue
            tex = tex.rotate(90 * orient)            # NWN orientation: quarter turns counter-clockwise
            x, y = i % w, i // w
            img.paste(tex, (x * TILE_PX, (h - 1 - y) * TILE_PX))
        if missing < len(tiles):
            img.save(path)
        return img
