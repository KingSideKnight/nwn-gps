"""Write text into RivaTuner Statistics Server's on-screen display.

RTSS draws its OSD inside fullscreen 3D games; other programs publish text to it
through the documented shared memory "RTSSSharedMemoryV2" (see the RTSS SDK
header RTSSSharedMemory.h). We claim one OSD slot under our own owner name and
release it on exit. Nothing is injected by us; RTSS must be running.
"""
import ctypes
import ctypes.wintypes as wt
import struct

FILE_MAP_ALL_ACCESS = 0xF001F
SIG_RTSS = 0x52545353          # 'RTSS'
OWNER = b"nwn-gps"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenFileMappingW.restype = wt.HANDLE
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]

# header offsets
H_SIG, H_VER = 0, 4
H_OSD_ENTRY_SIZE, H_OSD_ARR_OFF, H_OSD_ARR_SIZE, H_OSD_FRAME, H_BUSY = 20, 24, 28, 32, 36
# OSD entry offsets
E_OSD, E_OWNER, E_OSDEX = 0, 256, 512
OSD_LEN, OWNER_LEN, OSDEX_LEN = 256, 256, 4096


class RTSS:
    def __init__(self):
        self.h = self.view = None
        self.slot = None

    def _u32(self, off):
        return ctypes.c_uint32.from_address(self.view + off)

    def connect(self):
        """True if RTSS is running and its shared memory is valid."""
        if self.view:
            if self._u32(H_SIG).value == SIG_RTSS:
                return True
            self.close()
        self.h = k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, "RTSSSharedMemoryV2")
        if not self.h:
            return False
        self.view = k32.MapViewOfFile(self.h, FILE_MAP_ALL_ACCESS, 0, 0, 0)
        if not self.view or self._u32(H_SIG).value != SIG_RTSS or self._u32(H_VER).value < 0x20000:
            self.close()
            return False
        self.slot = None
        return True

    def _entries(self):
        size = self._u32(H_OSD_ENTRY_SIZE).value
        base = self.view + self._u32(H_OSD_ARR_OFF).value
        for i in range(1, self._u32(H_OSD_ARR_SIZE).value):   # entry 0 belongs to RTSS itself
            yield base + i * size

    def _owner(self, entry):
        return ctypes.string_at(entry + E_OWNER, OWNER_LEN).split(b"\0", 1)[0]

    def _claim(self):
        if self.slot and self._owner(self.slot) == OWNER:
            return self.slot
        entries = list(self._entries())
        for e in entries:                       # pass 1: our old slot
            if self._owner(e) == OWNER:
                self.slot = e
                return e
        for e in entries:                       # pass 2: a free slot
            if not self._owner(e):
                ctypes.memmove(e + E_OWNER, OWNER + b"\0", len(OWNER) + 1)
                self.slot = e
                return e
        return None

    def _write(self, entry, text):
        busy = self._u32(H_BUSY) if self._u32(H_VER).value >= 0x2000E else None
        if busy is not None:
            if busy.value & 1:                  # another client is writing; skip this frame
                return False
            busy.value |= 1
        try:
            data = text.encode("utf-8", "replace")
            if self._u32(H_VER).value >= 0x20007:
                buf = data[:OSDEX_LEN - 1] + b"\0"
                ctypes.memmove(entry + E_OSDEX, buf, len(buf))
            buf = data[:OSD_LEN - 1] + b"\0"
            ctypes.memmove(entry + E_OSD, buf, len(buf))
            self._u32(H_OSD_FRAME).value += 1
        finally:
            if busy is not None:
                busy.value &= ~1
        return True

    def show(self, text):
        """Publish `text` (RTSS hypertext allowed). Returns False if RTSS isn't available."""
        if not self.connect():
            return False
        e = self._claim()
        return bool(e) and self._write(e, text)

    def clear(self):
        """Release our slot."""
        if self.view and self.slot and self._owner(self.slot) == OWNER:
            self._write(self.slot, "")
            ctypes.memset(self.slot + E_OWNER, 0, OWNER_LEN)
            self._u32(H_OSD_FRAME).value += 1
        self.slot = None

    def close(self):
        if self.view:
            try:
                self.clear()
            except OSError:
                pass
            k32.UnmapViewOfFile(self.view)
        if self.h:
            k32.CloseHandle(self.h)
        self.h = self.view = self.slot = None
