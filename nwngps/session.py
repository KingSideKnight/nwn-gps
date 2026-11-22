"""Resilient view of the game: survives the game not running, menus, loading
screens, relogs, server changes and game restarts.

States:
  NO_GAME   nwmain.exe not running (keeps retrying)
  MENU      game running, no module (main menu, character select, connecting)
  LOADING   module present but area or character not readable yet
  IN_GAME   area + character position readable

`Session.poll()` returns a Snapshot; call it a few times a second.
"""
import struct
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import layout as L
from . import objects
from .memory import GameMemory

NO_GAME, MENU, LOADING, IN_GAME = "NO_GAME", "MENU", "LOADING", "IN_GAME"


@dataclass
class Snapshot:
    state: str
    t: float = field(default_factory=time.time)
    world: str = None        # e.g. "nwnarelith.com" (from NWSync URL) or module name
    server: str = None       # e.g. "ARE_CitiesAndPlanes"
    module: str = None
    area: str = None         # resref
    area_name: str = None
    tileset: str = None
    size: tuple = None
    pos: tuple = None
    facing: tuple = None
    area_ptr: int = None


def world_from(nwsync_url, module_name):
    host = urlparse(nwsync_url).hostname if nwsync_url else None
    if host:
        parts = host.split(".")
        return ".".join(parts[-2:])          # nwsync.nwnarelith.com -> nwnarelith.com
    return (module_name or "unknown").lower()


class Session:
    def __init__(self, log=print):
        self.log = log
        self.mem = None
        self.table = None
        self.table_area = None
        self.next_locate = 0.0
        self.state = None

    # --- attach / detach --------------------------------------------------
    def _attach(self):
        try:
            self.mem = GameMemory()
            self.vt = {k: self.mem.base + v for k, v in L.VTABLES.items()}
            self.table = None
            self.log(f"attached to nwmain.exe pid {self.mem.pid}")
            return True
        except (RuntimeError, OSError) as e:
            if "Access is denied" in str(e):
                self.log("can't read the game: it is running as administrator; start it normally")
            self.mem = None
            return False

    def _detach(self):
        if self.mem:
            self.mem.close()
        self.mem, self.table = None, None

    def close(self):
        self._detach()

    def _alive(self):
        # process gone? (reads of the module header fail once it exits)
        return self.mem and self.mem.read(self.mem.base, 2) == b"MZ"

    # --- reading ------------------------------------------------------------
    def _internal(self):
        m = self.mem
        p = m.u64(m.base + L.G_APP_MANAGER)
        for off in L.CHAIN_CLIENT_INTERNAL:
            p = m.u64(p + off) if p else None
        return p

    def _player(self, inn, area):
        """Our creature, via the player id and the object table."""
        m = self.mem
        pid = m.u32(inn + L.INTERNAL_PLAYER_ID)
        if self.table:
            cre = self.table.lookup(pid) if pid else None
            if cre and m.u64(cre) == self.vt["CNWCCreature"]:
                return cre
            if self.table.coverage(objects.area_ids(m, area)) < 0.8:
                self.table = None            # table moved (relog / reconnect)
        if not self.table and time.time() >= self.next_locate:
            self.next_locate = time.time() + 5.0
            self.table = objects.ObjectTable.locate(m, area, log=self.log)
            if self.table:
                cre = self.table.lookup(pid) if pid else None
                if cre and m.u64(cre) == self.vt["CNWCCreature"]:
                    return cre
        return None

    def _read(self):
        m = self.mem
        inn = self._internal()
        mod = m.u64(inn + L.INTERNAL_MODULE) if inn else None
        if not mod or m.u64(mod) != self.vt["CNWCModule"]:
            return Snapshot(MENU)
        module = m.exostring(mod + L.MODULE_NAME)
        if not module:
            return Snapshot(MENU)
        s = Snapshot(LOADING, module=module,
                     server=m.exostring(mod + L.MODULE_SERVER_NAME) or module,
                     world=world_from(m.exostring(mod + L.MODULE_NWSYNC_URL), module))
        area = m.u64(mod + L.MODULE_CURRENT_AREA)
        if not area or m.u64(area) != self.vt["CNWCArea"]:
            return s
        rr = lambda off: (m.read(area + off, 16) or b"").split(b"\0", 1)[0].decode("latin-1")
        s.area, s.tileset, s.area_ptr = rr(L.AREA_RESREF), rr(L.AREA_TILESET), area
        s.area_name = m.exostring(area + L.AREA_NAME)
        s.size = (m.u32(area + L.AREA_WIDTH), m.u32(area + L.AREA_HEIGHT))
        cre = self._player(inn, area)
        if not cre or m.u64(cre + L.OBJ_AREA) != area:
            return s
        b = m.read(cre + L.OBJ_POS, 24)
        if not b:
            return s
        s.pos = tuple(round(v, 2) for v in struct.unpack_from("<fff", b, 0))
        s.facing = tuple(round(v, 3) for v in struct.unpack_from("<fff", b, 12))
        s.state = IN_GAME
        return s

    def poll(self):
        if not self.mem and not self._attach():
            snap = Snapshot(NO_GAME)
        elif not self._alive():
            self.log("game exited")
            self._detach()
            snap = Snapshot(NO_GAME)
        else:
            try:
                snap = self._read()
            except (TypeError, struct.error):
                snap = Snapshot(LOADING)     # half-built objects during loads
        if snap.state != self.state:
            extra = f" ({snap.server}: {snap.area_name})" if snap.state == IN_GAME else ""
            self.log(f"state {self.state} -> {snap.state}{extra}")
            self.state = snap.state
        return snap
