"""Where things live, and the player's settings.

  Documents\\NWN GPS\\settings.json   settings you may edit (created on first run)
  Documents\\NWN GPS\\Exports, Inbox  map sharing
  Documents\\NWN GPS\\data            map databases, map image cache, backups
  Documents\\NWN GPS\\logs            logs

The game install is found automatically (running game, Steam libraries, GOG registry,
common Beamdog paths); set "game_dir" in settings.json if it isn't.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import uuid
import winreg
from pathlib import Path

APP = "NWN GPS"
SETTINGS_VERSION = 1


def known_folder(guid):
    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                    ("d4", ctypes.c_ubyte * 8)]
    u = uuid.UUID(guid)
    g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    p = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) != 0:
        return None
    path = Path(p.value)
    ctypes.windll.ole32.CoTaskMemFree(p)
    return path


def documents_dir():
    """The real Documents folder (it may be redirected, e.g. to OneDrive)."""
    return known_folder("FDD39AD0-238F-46AF-ADB4-6C85480369C7") or Path.home() / "Documents"


SHARE_DIR = documents_dir() / APP
SETTINGS_FILE = SHARE_DIR / "settings.json"
# Data lives under Documents (like NWN's own files), not AppData\Local: packaged Windows apps
# (MSIX) get AppData\Local silently redirected to a private copy, so a GPS started from one would
# not see the data of a GPS started from Explorer, and the game couldn't load DLLs placed there.
DATA_DIR = Path(os.environ.get("NWNGPS_DATA") or (SHARE_DIR / "data"))
LOG_DIR = SHARE_DIR / "logs"
OLD_LOCALAPPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP

DEFAULT_HOTKEYS = {
    "search": "Ctrl+Shift+F", "clear": "Ctrl+Shift+X", "map": "Ctrl+Shift+M", "hide": "Ctrl+Shift+G",
    "export": "Ctrl+Shift+E", "import": "Ctrl+Shift+I",
}
DEFAULTS = {
    "version": SETTINGS_VERSION,
    "game_dir": "",          # empty = auto-detect
    "user_dir": "",          # empty = Documents\Neverwinter Nights
    "hotkeys": DEFAULT_HOTKEYS,
    "accepted_notice": False,
}


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
        s["hotkeys"] = {**DEFAULT_HOTKEYS, **(saved.get("hotkeys") or {})}
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---- game install detection ---------------------------------------------------------
EXE_REL = Path("bin") / "win32" / "nwmain.exe"


def _valid(d):
    return d and (Path(d) / EXE_REL).exists() and (Path(d) / "data").is_dir()


def _running_game_dir():
    from .memory import find_pid
    pid = find_pid()
    if not pid:
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return Path(buf.value).parent.parent.parent       # ...\bin\win32\nwmain.exe
    finally:
        k32.CloseHandle(h)
    return None


def _reg(root, key, value):
    try:
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None


def _steam_dirs():
    roots = [_reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
             _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")]
    libs = []
    for r in filter(None, roots):
        r = Path(r)
        libs.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        try:
            libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8"))]
        except OSError:
            pass
    return [lib / "steamapps" / "common" / "Neverwinter Nights" for lib in dict.fromkeys(libs)]


def _gog_dirs():
    out = []
    for base in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    sub = winreg.EnumKey(k, i)
                    name = _reg(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{sub}", "gameName") or ""
                    if "neverwinter nights" in name.lower():
                        p = _reg(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{sub}", "path")
                        if p:
                            out.append(Path(p))
        except OSError:
            continue
    return out


def _beamdog_dirs():
    home = Path.home()
    return [home / "Beamdog Library" / "00829", home / "Beamdog Library" / "00785",
            Path(r"C:\Program Files (x86)\Beamdog\Neverwinter Nights")]


def game_dir(settings=None):
    """The NWN:EE install folder, or None. Remembers what it found in settings.json."""
    s = settings or load_settings()
    candidates = [s.get("game_dir"), _running_game_dir(), *_steam_dirs(), *_gog_dirs(), *_beamdog_dirs()]
    for c in candidates:
        if c and _valid(c):
            c = Path(c)
            if not s.get("game_dir"):
                s["game_dir"] = str(c)
                save_settings(s)
            return c
    return None


def user_dir(settings=None):
    """The NWN:EE user folder (Documents\\Neverwinter Nights unless set otherwise)."""
    s = settings or load_settings()
    return Path(s["user_dir"]) if s.get("user_dir") else documents_dir() / "Neverwinter Nights"


def frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    """Folder of the program itself: next to NWN-GPS.exe, or the source checkout."""
    return Path(sys.executable).parent if frozen() else Path(__file__).resolve().parent.parent


def bundle_dir():
    """Where bundled files (the DLL) are: the PyInstaller bundle, or the source checkout."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
