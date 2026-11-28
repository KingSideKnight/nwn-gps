"""Area maps from real tile art.

read_tiles(mem, area_ptr, w, h)      -> [(tile_id, orientation, height), ...] row-major from the SW corner
Maps(resources).image(tileset, w, h, tiles) -> PIL image (north up), cached in data/maps/

Each tile's minimap picture is the tileset's ImageMap2D texture (e.g. mi_tno01_a01_01.tga),
rotated by the tile's orientation.
"""
import hashlib
import io
import json
import os
import re
import struct

from PIL import Image

from . import layout as L
from .db import DATA_DIR

MAP_DIR = DATA_DIR / "maps"
TILE_PX = 32
MAX_AREA_TILES = 64                    # NWN areas are at most 32x32; anything bigger is bad data
MAX_TEXTURE_SIDE = 1024                # minimap textures are 16-64 px; refuse to decode giants
MAX_SET_BYTES = 16 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 4096 * 4096   # Pillow's decompression-bomb guard, tightened


def bioware_dds(data):
    """NWN's own DDS variant (custom tilesets, e.g. Arelith's tdm01): a 20-byte header
    (width, height, channels 3 = DXT1 / 4 = DXT5, bytes of the top level, alpha float) and then
    the mip levels. Returns the top level as a standard DDS file, or None if it isn't one."""
    if len(data) < 20 or data[:4] == b"DDS ":
        return None
    w, h, channels, size = struct.unpack_from("<4I", data)
    if channels not in (3, 4) or not (0 < w <= MAX_TEXTURE_SIDE and 0 < h <= MAX_TEXTURE_SIDE):
        return None
    block = 8 if channels == 3 else 16
    if size != max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block or len(data) < 20 + size:
        return None
    pixel_format = struct.pack("<II4s5I", 32, 0x4, b"DXT1" if channels == 3 else b"DXT5", 0, 0, 0, 0, 0)
    header = struct.pack("<7I44x", 124, 0x1007 | 0x80000, h, w, size, 0, 1) + pixel_format + \
        struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    return b"DDS " + header + data[20:20 + size]


def texture_size_ok(data):
    """Check a texture's declared size before decoding it (server-supplied content)."""
    if data[:4] == b"DDS ":
        h, w = struct.unpack_from("<II", data, 12)
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack_from(">II", data, 16)
    elif len(data) >= 18:                              # TGA has no magic; width/height at 12/14
        w, h = struct.unpack_from("<HH", data, 12)
    else:
        return False
    return 0 < w <= MAX_TEXTURE_SIDE and 0 < h <= MAX_TEXTURE_SIDE
CACHE_MAX_BYTES = 300 * 1024 * 1024    # cached area images are rebuilt on demand, so cap the folder


def prune_cache(max_bytes=CACHE_MAX_BYTES):
    """Delete least-recently-used cached map images (and walkable grids) until the folder fits in
    max_bytes."""
    files = [p for p in MAP_DIR.iterdir() if p.suffix == ".png" or p.suffix.startswith(".walk")]
    files.sort(key=lambda p: max(p.stat().st_atime, p.stat().st_mtime))
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for p in files:
        if total <= max_bytes:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
        removed += 1
    return removed


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


def area_layout(store, mem, snap):
    """(tileset, w, h, tiles) of the area you're in (from live memory, else the recorded layout),
    or None."""
    tiles = read_tiles(mem, snap.area_ptr, *snap.size) if (snap.size and mem) else None
    if tiles:
        return (snap.tileset, *snap.size, tiles)
    return store.tiles(snap.area)


def area_image(maps, store, mem, snap, log=print, layout=None):
    """Tile-art map of the area you're in (from live memory, else the recorded layout), or None."""
    import time
    try:
        layout = layout or area_layout(store, mem, snap)
        if not layout:
            return None
        tileset, w, h, tiles = layout
        t0 = time.time()
        img = maps.image(tileset, w, h, tiles)
        log(f"map: {snap.area_name} ({w}x{h} {tileset}) in {time.time() - t0:.2f}s")
        return img
    except Exception as e:     # a map is a nice-to-have: never break navigation over it
        log(f"map unavailable for {snap.area}: {e!r}")
        return None


class Maps:
    def __init__(self, resources):
        self.res = resources
        self.sets = {}
        self.textures = {}
        MAP_DIR.mkdir(parents=True, exist_ok=True)
        prune_cache()

    def is_interior(self, name):
        """The tileset's [GENERAL] Interior flag (buildings, dungeons) - None if unknown."""
        key = ("interior", name)
        if key not in self.sets:
            data = self.res.get(name, "set") if name else None
            data = data if data and len(data) <= MAX_SET_BYTES else None
            m = re.search(rb"^Interior=(\d)", data or b"", re.M)
            self.sets[key] = (m.group(1) == b"1") if m else None
        return self.sets[key]

    def tileset(self, name):
        if name not in self.sets:
            data = self.res.get(name, "set")
            ok = data and len(data) <= MAX_SET_BYTES
            self.sets[name] = parse_set(data.decode("latin-1")) if ok else {}
        return self.sets[name]

    def texture(self, resref):
        if resref not in self.textures:
            img = None
            for ext in ("tga", "dds", "png"):
                data = self.res.get(resref, ext)
                if data and ext == "dds" and data[:4] != b"DDS ":
                    data = bioware_dds(data)
                if data and texture_size_ok(data):
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
        if not (isinstance(w, int) and isinstance(h, int) and 1 <= w <= MAX_AREA_TILES
                and 1 <= h <= MAX_AREA_TILES and len(tiles) == w * h):
            raise ValueError(f"implausible area size {w}x{h} ({len(tiles)} tiles)")
        path = MAP_DIR / f"{self.key(tileset, w, h, tiles)}.png"
        if path.exists():
            try:
                with Image.open(path) as cached:
                    img = cached.convert("RGBA")
                path.touch()                   # Windows doesn't always update access times: mark it used
                return img
            except OSError:                    # damaged (e.g. an old half-written file): draw it again
                pass
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
            save_atomic(img, path)
        return img


def save_atomic(img, path):
    """Write the PNG under a temporary name, then swap it in, so the other GPS windows (which share
    this cache) never open a half-written file. Losing the race just means the other copy stays."""
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    try:
        img.save(tmp, format="PNG")
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        tmp.unlink(missing_ok=True)
