"""One running copy per part (named Windows mutex; released automatically when the process exits)."""
import ctypes
import sys

ERROR_ALREADY_EXISTS = 183
_held = []


def single_instance(name):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, False, f"Local\\nwngps_{name}")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        sys.exit(f"NWN GPS {name} is already running")
    _held.append(h)
