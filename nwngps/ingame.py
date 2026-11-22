"""In-game GPS panel (works in exclusive fullscreen).

  python -m nwngps.ingame ["<destination>"]
  python -m nwngps.cli go "<destination>"      change destination while it runs

Loads native/build/nwngps_gl.dll into the running game (no game files change),
publishes the panel image through shared memory ~10x a second, and on Ctrl+C
tells the DLL to unhook and unload itself. If this program dies, the DLL hides
the panel after 3 s. Re-injects automatically if the game restarts.
"""
import ctypes
import ctypes.wintypes as wt
import mmap
import struct
import sys
import time
from pathlib import Path

from . import panel
from .db import Store
from .hud import read_target, set_target
from .memory import MODULEENTRY32W, TH32CS_SNAPMODULE, k32
from .nav import Navigator
from .session import IN_GAME, Session

DLL = Path(__file__).resolve().parent.parent / "native" / "build" / "nwngps_gl.dll"
SHM_NAME = "nwngps_overlay"
MAGIC, VERSION = 0x5350474E, 1
MAX_W, MAX_H, HDR = 640, 1024, 192
SHM_SIZE = HDR + MAX_W * MAX_H * 4
FLAG_VISIBLE, FLAG_UNLOAD = 1, 2
O_SEQ, O_W, O_H, O_OFFX, O_OFFY, O_ANCHOR, O_FLAGS = 8, 12, 16, 20, 24, 28, 32
O_STATE, O_FRAMES, O_VIEW_W, O_VIEW_H, O_MSG = 36, 40, 44, 48, 64
STATES = {0: "unloaded", 1: "attached", 2: "hooked", 3: "drawing", 9: "error"}

PROCESS_INJECT = 0x0002 | 0x0400 | 0x0008 | 0x0020 | 0x0010   # create thread, query, vm op/write/read
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


def module_loaded(pid, name):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    m = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
    try:
        ok = k32.Module32FirstW(snap, ctypes.byref(m))
        while ok:
            if m.szModule.lower() == name.lower():
                return True
            ok = k32.Module32NextW(snap, ctypes.byref(m))
    finally:
        k32.CloseHandle(snap)
    return False


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


class Shm:
    def __init__(self):
        self.m = mmap.mmap(-1, SHM_SIZE, tagname=SHM_NAME)
        if self.u32(0) != MAGIC:
            struct.pack_into("<II", self.m, 0, MAGIC, VERSION)
        struct.pack_into("<iiI", self.m, O_OFFX, 16, 16, 0)
        self.set_flags(FLAG_VISIBLE)

    def u32(self, off):
        return struct.unpack_from("<I", self.m, off)[0]

    def set_flags(self, f):
        struct.pack_into("<I", self.m, O_FLAGS, f)

    def publish(self, img):
        w, h = img.size
        seq = self.u32(O_SEQ)
        seq = seq + 1 if seq % 2 == 0 else seq          # odd: writing
        struct.pack_into("<I", self.m, O_SEQ, seq)
        struct.pack_into("<II", self.m, O_W, w, h)
        self.m[HDR:HDR + w * h * 4] = img.tobytes()
        struct.pack_into("<I", self.m, O_SEQ, seq + 1)  # even: done

    def status(self):
        msg = bytes(self.m[O_MSG:O_MSG + 128]).split(b"\0", 1)[0].decode(errors="replace")
        return self.u32(O_STATE), self.u32(O_FRAMES), msg

    def close(self):
        self.m.close()


def main():
    if len(sys.argv) > 1:
        set_target(" ".join(sys.argv[1:]))
    if not DLL.exists():
        sys.exit(f"{DLL} not built: run native\\build.cmd")
    store, session, shm = Store(), Session(log=log), Shm()
    nav, query, pois, pois_area, injected_pid = None, object(), [], None, None
    last_status = None
    log("in-game GPS running (Ctrl+C to stop)")
    try:
        while True:
            t0 = time.time()
            snap = session.poll()
            pid = session.mem.pid if session.mem else None
            if pid and pid != injected_pid and snap.state != "NO_GAME":
                if module_loaded(pid, DLL.name):
                    log("DLL already loaded in the game; reusing it")
                else:
                    log(f"loading {DLL.name} into nwmain.exe pid {pid}")
                    if not inject(pid, DLL):
                        log("injection failed")
                injected_pid = pid
            q = read_target()
            if q != query:
                query, nav = q, None
                hits = store.search(q) if q else []
                if hits:
                    nav = Navigator(store, hits[0])
                    log(f"destination: {hits[0]['name']} in {store.area_name(hits[0]['area'])}")
            if snap.state == IN_GAME and snap.area != pois_area:
                pois = store.db.execute("SELECT kind,name,x,y FROM pois WHERE area=?", (snap.area,)).fetchall()
                pois_area = snap.area
            g = nav.update(snap) if nav else None
            shm.publish(panel.render(snap, g, pois, snap.size))
            st = shm.status()
            if st[0] != (last_status or (None,))[0] or st[2] != (last_status or (0, 0, ""))[2]:
                log(f"DLL: {STATES.get(st[0], st[0])}  frames={st[1]}  {st[2]}")
                last_status = st
            time.sleep(max(0.0, 0.1 - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if injected_pid:
            log("unloading the DLL from the game...")
            shm.set_flags(FLAG_UNLOAD)
            for _ in range(50):
                if shm.status()[0] == 0:
                    break
                time.sleep(0.1)
            st = shm.status()
            log("DLL unloaded" if st[0] == 0 else f"DLL did not confirm unload (state {st[0]}); "
                                                  "it hides the panel and unloads on its next frame")
        shm.close()
        session.close()
        store.close()


if __name__ == "__main__":
    main()
