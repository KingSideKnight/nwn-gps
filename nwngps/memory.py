"""Read-only access to a running nwmain.exe.

The process handle is opened with PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
only, so nothing here can modify the game's memory.
"""
import ctypes
import ctypes.wintypes as wt
import struct

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPMODULE = 0x8 | 0x10
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}  # RO, RW, WC, XR, XRW, XWC

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
                ("hModule", wt.HMODULE), ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD)]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                               ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t


def find_pid(exe_name="nwmain.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == exe_name.lower():
                return e.th32ProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


class GameMemory:
    def __init__(self, exe_name="nwmain.exe"):
        self.pid = find_pid(exe_name)
        if not self.pid:
            raise RuntimeError(f"{exe_name} is not running")
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.h:
            raise ctypes.WinError(ctypes.get_last_error())
        self.base = self._module_base(exe_name)

    def _module_base(self, exe_name):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, self.pid)
        m = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
        try:
            ok = k32.Module32FirstW(snap, ctypes.byref(m))
            while ok:
                if m.szModule.lower() == exe_name.lower():
                    return m.modBaseAddr
                ok = k32.Module32NextW(snap, ctypes.byref(m))
        finally:
            k32.CloseHandle(snap)
        raise RuntimeError("module base not found")

    def close(self):
        k32.CloseHandle(self.h)

    # --- primitive reads -------------------------------------------------
    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
            return None
        return buf.raw[:n.value]

    def u64(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b and len(b) == 8 else None

    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b and len(b) == 4 else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<f", b)[0] if b and len(b) == 4 else None

    def cstr(self, addr, maxlen=256):
        b = self.read(addr, maxlen)
        if not b:
            return None
        b = b.split(b"\0", 1)[0]
        return b.decode("latin-1")

    def exostring(self, addr):
        """CExoString = { char* m_sString; uint32 m_nBufferLength }"""
        p = self.u64(addr)
        if not p:
            return None
        return self.cstr(p)

    # --- region walking --------------------------------------------------
    def regions(self, private_only=True):
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while k32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE
                    and not mbi.Protect & PAGE_GUARD
                    and (not private_only or mbi.Type == MEM_PRIVATE)):
                yield base, size
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break

    def scan_many(self, patterns, private_only=True, align=8, chunk=16 << 20):
        """Read memory once, look for several same-length byte patterns.
        Yields (pattern, address)."""
        for base, size in self.regions(private_only):
            pos = 0
            while pos < size:
                n = min(chunk, size - pos)
                data = self.read(base + pos, n)
                if data:
                    for p in patterns:
                        i = data.find(p)
                        while i >= 0:
                            if (base + pos + i) % align == 0:
                                yield p, base + pos + i
                            i = data.find(p, i + 1)
                pos += n

    def scan(self, pattern, private_only=True, align=1, chunk=16 << 20):
        """Yield addresses where `pattern` (bytes) occurs."""
        plen = len(pattern)
        for base, size in self.regions(private_only):
            pos = 0
            while pos < size:
                n = min(chunk, size - pos)
                data = self.read(base + pos, n + plen - 1 if pos + n < size else n)
                if data:
                    i = data.find(pattern)
                    while i >= 0:
                        if i < n and (base + pos + i) % align == 0:
                            yield base + pos + i
                        i = data.find(pattern, i + 1)
                pos += n
