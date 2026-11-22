"""In-game GPS panel (works in exclusive fullscreen).

  python -m nwngps.ingame ["<destination>"]

In the game:
  Ctrl+Shift+F   destination picker (type to search, Up/Down, Enter, Esc)
  Ctrl+Shift+X   clear the destination (it also clears itself 10 s after you arrive)
  Ctrl+Shift+G   show / hide the panel
  Ctrl+Shift + drag the panel with the left mouse button to move it (position is saved)

Loads the DLL from native/build into the running game (no game files change;
a content-hashed copy is loaded so rebuilds never collide with a loaded file),
publishes the panel image through shared memory, reads hotkey/picker events
back, and on Ctrl+C tells the DLL to unhook and unload itself. If this program
dies, the DLL hides the panel after 3 s. Re-injects if the game restarts, and
replaces an older DLL version that is still loaded.
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import mmap
import shutil
import struct
import sys
import time
from pathlib import Path

from . import panel
from .db import DATA_DIR, Store
from .hud import read_target, resolve_target, set_target
from .memory import MODULEENTRY32W, TH32CS_SNAPMODULE, k32
from .nav import Navigator
from .picker import EV_CHAR, EV_CLEAR, EV_KEY, EV_MOVED, EV_OPEN, EV_TOGGLE, Picker

AUTO_CLEAR_AFTER = 10.0   # seconds standing at the destination before it clears itself
KEY_NAMES = {0x0D: "Enter", 0x1B: "Esc", 0x26: "Up", 0x28: "Down", 0x08: "Backspace", 0x2E: "Delete",
             0x09: "Tab", 0x21: "PgUp", 0x22: "PgDn", 0x24: "Home", 0x23: "End"}
from .session import IN_GAME, Session

BUILD = Path(__file__).resolve().parent.parent / "native" / "build"
RUNTIME = DATA_DIR / "runtime"
DLL_PREFIX = "nwngps_gl"
DLL_VERSION = 2

SHM_NAME = "nwngps_overlay_v2"
MAGIC = 0x5350474E
MAX_W, MAX_H, HDR = 640, 1024, 2048
SHM_SIZE = HDR + MAX_W * MAX_H * 4
LEGACY_SHM = ("nwngps_overlay", 192 + 640 * 1024 * 4)     # v1 DLL
FLAG_VISIBLE, FLAG_UNLOAD = 1, 2
O_SEQ, O_W, O_H, O_OFFX, O_OFFY, O_ANCHOR, O_FLAGS = 8, 12, 16, 20, 24, 28, 32
O_STATE, O_FRAMES, O_VIEW_W, O_VIEW_H = 36, 40, 44, 48
O_DLLVER, O_CAPTURING, O_EVHEAD, O_MSG, O_EVENTS = 52, 56, 60, 64, 192
EV_RING = 64
STATES = {0: "unloaded", 1: "attached", 2: "hooked", 3: "drawing", 9: "error"}

PROCESS_INJECT = 0x0002 | 0x0400 | 0x0008 | 0x0020 | 0x0010
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
k32.CreateRemoteThread.restype = wt.HANDLE
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                   ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.GetModuleHandleW.restype = wt.HMODULE
k32.GetProcAddress.restype = ctypes.c_void_p
k32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def our_modules(pid):
    """Names of our DLLs currently loaded in the game."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    m = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
    out = []
    try:
        ok = k32.Module32FirstW(snap, ctypes.byref(m))
        while ok:
            if m.szModule.lower().startswith(DLL_PREFIX):
                out.append(m.szModule.lower())
            ok = k32.Module32NextW(snap, ctypes.byref(m))
    finally:
        k32.CloseHandle(snap)
    return out


def runtime_dll():
    """Newest build, copied to data/runtime/nwngps_gl-<hash>.dll (the file actually loaded)."""
    builds = [p for p in (BUILD / "nwngps_gl_new.dll", BUILD / "nwngps_gl.dll") if p.exists()]
    if not builds:
        sys.exit("DLL not built: run native\\build.cmd")
    src = max(builds, key=lambda p: p.stat().st_mtime)
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
    RUNTIME.mkdir(parents=True, exist_ok=True)
    dst = RUNTIME / f"{DLL_PREFIX}-{digest}.dll"
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def inject(pid, dll_path):
    """LoadLibraryW(dll_path) inside the game via a remote thread."""
    h = k32.OpenProcess(PROCESS_INJECT, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        path = str(dll_path).encode("utf-16-le") + b"\0\0"
        mem = k32.VirtualAllocEx(h, None, len(path), 0x3000, 0x04)
        k32.WriteProcessMemory(h, mem, path, len(path), None)
        load = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        t = k32.CreateRemoteThread(h, None, 0, load, mem, 0, None)
        if not t:
            raise ctypes.WinError(ctypes.get_last_error())
        k32.WaitForSingleObject(t, 10000)
        code = wt.DWORD()
        k32.GetExitCodeThread(t, ctypes.byref(code))
        k32.CloseHandle(t)
        k32.VirtualFreeEx(h, mem, 0, 0x8000)
        return code.value != 0
    finally:
        k32.CloseHandle(h)


UI_FILE = DATA_DIR / "ui.json"
ANCHORS = ["top-right", "top-left", "bottom-right", "bottom-left"]
# Default: bottom-right, raised clear of NWN's compass in that corner (drag to fine-tune).
DEFAULT_POS = {"anchor": 2, "off_x": 16, "off_y": 230}


def load_position():
    try:
        p = json.loads(UI_FILE.read_text())
        return {k: int(p[k]) for k in DEFAULT_POS}
    except (OSError, ValueError, KeyError, TypeError):
        return dict(DEFAULT_POS)


def save_position(pos):
    DATA_DIR.mkdir(exist_ok=True)
    UI_FILE.write_text(json.dumps(pos))


class Shm:
    def __init__(self):
        self.m = mmap.mmap(-1, SHM_SIZE, tagname=SHM_NAME)
        struct.pack_into("<II", self.m, 0, MAGIC, DLL_VERSION)
        self.set_position(load_position())
        self.set_flags(FLAG_VISIBLE)
        self.ev_tail = self.u32(O_EVHEAD)

    def set_position(self, pos):
        struct.pack_into("<iiI", self.m, O_OFFX, pos["off_x"], pos["off_y"], pos["anchor"])

    def position(self):
        off_x, off_y, anchor = struct.unpack_from("<iiI", self.m, O_OFFX)
        return {"anchor": anchor, "off_x": off_x, "off_y": off_y}

    def u32(self, off):
        return struct.unpack_from("<I", self.m, off)[0]

    def set_flags(self, f):
        struct.pack_into("<I", self.m, O_FLAGS, f)

    def flags(self):
        return self.u32(O_FLAGS)

    def publish(self, img):
        w, h = img.size
        seq = self.u32(O_SEQ)
        seq = seq + 1 if seq % 2 == 0 else seq
        struct.pack_into("<I", self.m, O_SEQ, seq)
        struct.pack_into("<II", self.m, O_W, w, h)
        self.m[HDR:HDR + w * h * 4] = img.tobytes()
        struct.pack_into("<I", self.m, O_SEQ, seq + 1)

    def events(self):
        head = self.u32(O_EVHEAD)
        if head - self.ev_tail > EV_RING:
            self.ev_tail = head - EV_RING
        out = []
        while self.ev_tail < head:
            t, code, mods, _ = struct.unpack_from("<IIII", self.m, O_EVENTS + (self.ev_tail % EV_RING) * 16)
            out.append((t, code, mods))
            self.ev_tail += 1
        return out

    def status(self):
        msg = bytes(self.m[O_MSG:O_MSG + 128]).split(b"\0", 1)[0].decode(errors="replace")
        return self.u32(O_STATE), self.u32(O_FRAMES), msg, self.u32(O_DLLVER)

    def close(self):
        self.m.close()


def unload_old(pid, shm):
    """Ask any loaded copy of our DLL (v1 or older v2) to unload; wait until it's gone."""
    shm.set_flags(FLAG_UNLOAD)
    try:
        legacy = mmap.mmap(-1, LEGACY_SHM[1], tagname=LEGACY_SHM[0])
        flags = struct.unpack_from("<I", legacy, 32)[0]
        struct.pack_into("<I", legacy, 32, flags | FLAG_UNLOAD)
    except OSError:
        legacy = None
    for _ in range(60):
        if not our_modules(pid):
            break
        time.sleep(0.1)
    if legacy:
        legacy.close()
    shm.set_flags(FLAG_VISIBLE)
    return not our_modules(pid)


class InGame:
    def __init__(self):
        self.store, self.session, self.shm = Store(), Session(log=log), Shm()
        self.picker = Picker(self.store)
        self.dll = runtime_dll()
        self.nav, self.target, self.pois, self.pois_area = None, object(), [], None
        self.injected_pid, self.last_status, self.last_key, self.last_publish = None, None, None, 0.0
        self.visible = True
        self.arrived_at = None

    def ensure_dll(self, pid):
        loaded = our_modules(pid)
        if self.dll.name.lower() in loaded:
            log(f"{self.dll.name} already loaded; reusing it")
        else:
            if loaded:
                log(f"replacing loaded {', '.join(loaded)} with {self.dll.name}")
                if not unload_old(pid, self.shm):
                    log("old DLL did not unload (is the game minimised? it unloads on its next frame)")
                    return False
            log(f"loading {self.dll.name} into nwmain.exe pid {pid}")
            if not inject(pid, self.dll):
                log("injection failed")
                return False
        self.injected_pid = pid
        return True

    def handle_events(self):
        for t, code, _mods in self.shm.events():
            if t == EV_TOGGLE:
                self.visible = not self.visible
                self.shm.set_flags(FLAG_VISIBLE if self.visible else 0)
                log(f"hotkey: panel {'shown' if self.visible else 'hidden'}")
            elif t == EV_CLEAR:
                log("hotkey: clear destination")
                set_target(None)
            elif t == EV_MOVED:
                pos = self.shm.position()
                save_position(pos)
                log(f"panel moved: {ANCHORS[pos['anchor']] if pos['anchor'] < 4 else pos['anchor']} "
                    f"+{pos['off_x']},{pos['off_y']} (saved)")
            elif t == EV_OPEN:
                self.picker.start(has_destination=self.nav is not None)
                self.shm.set_flags(FLAG_VISIBLE)
                log(f"picker opened ({len(self.picker.results)} entries)")
            elif t in (EV_CHAR, EV_KEY):
                if t == EV_KEY:
                    log(f"picker key {KEY_NAMES.get(code, hex(code))} (query {self.picker.query!r}, "
                        f"selected {self.picker.sel})")
                res = self.picker.handle(t, code)
                if res:
                    action, pick = res
                    log(f"picker: {action}" + (f" {pick['name']}" if pick else ""))
                    if action == "pick":
                        set_target(None, pick=pick)
                    elif action == "clear":
                        set_target(None)
                    if not self.visible:
                        self.shm.set_flags(0)
            else:
                log(f"unknown event {t} {code}")

    def auto_clear(self, g):
        """Clear the destination once you've been there for a few seconds."""
        if g and g.status == "ARRIVED":
            self.arrived_at = self.arrived_at or time.time()
            g.line2 = f"Destination clears in {max(0, AUTO_CLEAR_AFTER - (time.time() - self.arrived_at)):.0f} s"
            if time.time() - self.arrived_at >= AUTO_CLEAR_AFTER:
                log("arrived; destination cleared")
                set_target(None)
                self.arrived_at = None
        else:
            self.arrived_at = None

    def update_target(self):
        tgt = read_target()
        if tgt != self.target:
            self.target = tgt
            dest = resolve_target(self.store, tgt)
            self.nav = Navigator(self.store, dest) if dest else None
            log(f"destination: {dest['name']} in {self.store.area_name(dest['area'])}" if dest
                else "destination cleared")

    def frame(self):
        snap = self.session.poll()
        pid = self.session.mem.pid if self.session.mem else None
        if pid and pid != self.injected_pid and snap.state != "NO_GAME":
            self.ensure_dll(pid)
        self.handle_events()
        self.update_target()
        if snap.state == IN_GAME and snap.area != self.pois_area:
            self.pois = self.store.db.execute("SELECT kind,name,x,y FROM pois WHERE area=?", (snap.area,)).fetchall()
            self.pois_area = snap.area
        g = self.nav.update(snap) if self.nav else None
        self.auto_clear(g)
        if self.picker.open:
            key = ("picker", self.picker.query, self.picker.sel, len(self.picker.results))
        else:
            key = (snap.state, snap.area, len(self.pois),
                   tuple(round(v * 2) for v in snap.pos[:2]) if snap.pos else None,
                   tuple(round(v, 1) for v in snap.facing[:2]) if snap.facing else None,
                   (g.status, g.line1, g.line2, round(g.distance or 0), g.target) if g else None)
        if key != self.last_key or time.time() - self.last_publish > 1.0:
            img = (panel.render_picker(self.picker, self.store.area_name) if self.picker.open
                   else panel.render(snap, g, self.pois, snap.size))
            self.shm.publish(img)
            self.last_key, self.last_publish = key, time.time()
        st = self.shm.status()
        if self.last_status is None or st[0] != self.last_status[0] or st[2] != self.last_status[2]:
            log(f"DLL v{st[3]}: {STATES.get(st[0], st[0])}  frames={st[1]}  {st[2]}")
            self.last_status = st

    def run(self):
        log("in-game GPS running (Ctrl+C to stop).  In game: Ctrl+Shift+F search, "
            "Ctrl+Shift+X clear, Ctrl+Shift+G hide")
        try:
            while True:
                t0 = time.time()
                self.frame()
                time.sleep(max(0.0, (0.03 if self.picker.open else 0.1) - (time.time() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            if self.injected_pid:
                log("unloading the DLL from the game...")
                gone = unload_old(self.injected_pid, self.shm) if our_modules(self.injected_pid) else True
                self.shm.set_flags(FLAG_UNLOAD)   # in case it was minimised: unload on its next frame
                log("DLL unloaded" if gone else "DLL will unload on the game's next frame")
            self.shm.close()
            self.session.close()
            self.store.close()


def main():
    if len(sys.argv) > 1:
        set_target(" ".join(sys.argv[1:]))
    InGame().run()


if __name__ == "__main__":
    main()
