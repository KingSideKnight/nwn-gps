"""Read-only access to game resources by (resref, type), NWN:EE style.

Lookup order: NWSync (the server's content, newest manifest of the world) ->
ERF texture packs (data/txpk) -> KEY/BIF archives (data/*.key). Nothing is written.
"""
import sqlite3
import struct
from compression import zstd
from pathlib import Path

from . import config

RESTYPE = {"tga": 3, "txi": 2022, "set": 2013, "mdl": 2002, "dds": 2033, "are": 2012, "plt": 6, "png": 0x0BD8}
RESTYPE_EXT = {v: k for k, v in RESTYPE.items()}


MAX_RESOURCE_BYTES = 64 * 1024 * 1024   # server content is untrusted: no decompression bombs


def nsyc_decode(blob):
    """NWSync blob: 'NSYC', version, algorithm (0 none, 2 zstd), uncompressed size, [zstd hdr] payload.
    Server-supplied, so output is capped at MAX_RESOURCE_BYTES and must match the declared size."""
    if blob[:4] != b"NSYC":
        return blob
    _ver, algo, size = struct.unpack_from("<III", blob, 4)
    if size > MAX_RESOURCE_BYTES:
        raise ValueError(f"NWSync resource too large ({size} bytes)")
    if algo == 0:
        return blob[16:16 + size]
    if algo == 2:
        start = blob.find(b"\x28\xb5\x2f\xfd", 16)     # zstd frame magic
        if start < 0:
            raise ValueError("NWSync resource: no zstd frame")
        d = zstd.ZstdDecompressor()
        out = d.decompress(blob[start:], max_length=size + 1)
        if len(out) != size or not d.eof:
            raise ValueError("NWSync resource: size doesn't match its header")
        return out
    raise ValueError(f"unsupported NSYC compression {algo}")


class NWSync:
    def __init__(self, origin_host=None, user_dir=None):
        """origin_host: part of the server's NWSync URL (e.g. 'nwnarelith.com'); None = no server content."""
        d = Path(user_dir or config.user_dir()) / "nwsync"
        self.meta = sqlite3.connect(f"file:{d / 'nwsyncmeta.sqlite3'}?mode=ro", uri=True)
        q = "select sha1, origin_url from manifests order by last_used_at desc"
        rows = self.meta.execute(q).fetchall()
        rows = [r for r in rows if origin_host and origin_host in r[1]]
        self.manifest = rows[0][0] if rows else None
        self.shards = [sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in sorted(d.glob("nwsyncdata_*.sqlite3"))]

    def get(self, resref, restype):
        if not self.manifest:
            return None
        r = self.meta.execute("select resref_sha1 from manifest_resrefs where manifest_sha1=? and resref=? "
                              "and restype=?", (self.manifest, resref.lower(), restype)).fetchone()
        if not r:
            return None
        for s in self.shards:
            row = s.execute("select data from resrefs where sha1=?", (r[0],)).fetchone()
            if row:
                try:
                    return nsyc_decode(row[0])
                except (ValueError, zstd.ZstdError):
                    return None                       # bad/hostile blob: treat as missing
        return None


class ERF:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            h = f.read(160)
            ver = h[4:8]
            count, = struct.unpack_from("<I", h, 16)
            key_off, res_off = struct.unpack_from("<II", h, 24)
            rlen = 32 if ver == b"V1.1" else 16
            esize = rlen + 8
            f.seek(key_off)
            keys = f.read(count * esize)
            f.seek(res_off)
            res = f.read(count * 8)
        self.index = {}
        for i in range(count):
            name = keys[i * esize:i * esize + rlen].split(b"\0", 1)[0].decode("latin-1").lower()
            rtype, = struct.unpack_from("<H", keys, i * esize + rlen + 4)
            off, size = struct.unpack_from("<II", res, i * 8)
            self.index[(name, rtype)] = (off, size)

    def get(self, resref, restype):
        e = self.index.get((resref.lower(), restype))
        if not e:
            return None
        with open(self.path, "rb") as f:
            f.seek(e[0])
            return f.read(e[1])


class KeyBif:
    def __init__(self, key_path):
        data = key_path.read_bytes()
        nbif, nkey, off_files, off_keys = struct.unpack_from("<IIII", data, 8)
        self.bifs = []
        for i in range(nbif):
            _size, name_off, name_len, _drives = struct.unpack_from("<IIHH", data, off_files + i * 12)
            name = data[name_off:name_off + name_len].split(b"\0", 1)[0].decode().replace("\\", "/")
            self.bifs.append(key_path.parent.parent / name)
        self.index = {}
        for i in range(nkey):
            o = off_keys + i * 22
            name = data[o:o + 16].split(b"\0", 1)[0].decode("latin-1").lower()
            rtype, rid = struct.unpack_from("<HI", data, o + 16)
            self.index[(name, rtype)] = rid
        self._bif_tables = {}

    def _table(self, bi):
        if bi not in self._bif_tables:
            with open(self.bifs[bi], "rb") as f:
                h = f.read(20)
                nvar, _nfix, off = struct.unpack_from("<III", h, 8)
                f.seek(off)
                raw = f.read(nvar * 16)
            self._bif_tables[bi] = {struct.unpack_from("<I", raw, i * 16)[0] & 0xFFFFF:
                                    struct.unpack_from("<II", raw, i * 16 + 4) for i in range(nvar)}
        return self._bif_tables[bi]

    def get(self, resref, restype):
        rid = self.index.get((resref.lower(), restype))
        if rid is None:
            return None
        bi, ri = rid >> 20, rid & 0xFFFFF
        if bi >= len(self.bifs) or not self.bifs[bi].exists():
            return None
        e = self._table(bi).get(ri)
        if not e:
            return None
        with open(self.bifs[bi], "rb") as f:
            f.seek(e[0])
            return f.read(e[1])


class Resources:
    def __init__(self, nwsync_host=None, game_dir=None):
        """nwsync_host: the connected server's NWSync host (from the world name), so its
        custom tilesets are used; base game content always comes after it."""
        self.sources = []
        if nwsync_host:
            try:
                self.sources.append(NWSync(nwsync_host))
            except sqlite3.Error:
                pass
        game = Path(game_dir) if game_dir else config.game_dir()
        if game is None:
            raise FileNotFoundError("Neverwinter Nights install not found: set game_dir in "
                                    f"{config.SETTINGS_FILE}")
        for p in sorted((game / "data" / "txpk").glob("*.erf")):
            self.sources.append(ERF(p))
        for k in ("nwn_retail.key", "nwn_base.key"):
            if (game / "data" / k).exists():
                self.sources.append(KeyBif(game / "data" / k))

    def get(self, resref, ext):
        rtype = RESTYPE[ext] if isinstance(ext, str) else ext
        for s in self.sources:
            data = s.get(resref, rtype)
            if data is not None:
                return data
        return None
