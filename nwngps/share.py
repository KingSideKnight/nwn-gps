"""Map sharing for players: easy folders and background export / import.

  Documents\\NWN GPS\\Exports   your exported maps (Ctrl+Shift+E), send these to friends
  Documents\\NWN GPS\\Inbox     drop friends' maps here, then Ctrl+Shift+I merges them
  Documents\\NWN GPS\\Inbox\\merged   files that were merged (kept, never deleted)

Your own database is backed up before every import (data/backups).
"""
import ctypes
import shutil
import threading
import time
import uuid
from pathlib import Path

from .db import Store


def documents_dir():
    """The real Documents folder (it may be redirected, e.g. to OneDrive)."""
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                        ("d4", ctypes.c_ubyte * 8)]
        u = uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7")      # FOLDERID_Documents
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            path = Path(p.value)
            ctypes.windll.ole32.CoTaskMemFree(p)
            return path
    except (AttributeError, OSError):
        pass
    return Path.home() / "Documents"


SHARE_DIR = documents_dir() / "NWN GPS"
EXPORTS, INBOX = SHARE_DIR / "Exports", SHARE_DIR / "Inbox"
MERGED = INBOX / "merged"


def ensure_folders():
    for d in (EXPORTS, INBOX, MERGED):
        d.mkdir(parents=True, exist_ok=True)


def inbox_files():
    return sorted(p for p in INBOX.glob("*.sqlite") if p.is_file()) if INBOX.exists() else []


def short(path):
    """'Documents\\NWN GPS\\Exports\\x.sqlite' style path for on-screen messages."""
    try:
        return str(Path("Documents") / Path(path).relative_to(documents_dir()))
    except ValueError:
        return str(path)


class Jobs:
    """Runs export/import off the game loop; posts status messages via `notify(text, kind)`."""

    def __init__(self, world, notify):
        self.world, self.notify = world, notify
        self.busy = threading.Lock()

    def _run(self, name, fn):
        if not self.busy.acquire(blocking=False):
            self.notify("Busy - a map export/import is already running", "warn")
            return
        def work():
            try:
                fn()
            except Exception as e:      # tell the player, never crash the GPS
                self.notify(f"{name} failed: {e}", "error")
            finally:
                self.busy.release()
        self.thread = threading.Thread(target=work, daemon=True, name=f"nwngps-{name}")
        self.thread.start()

    def export(self):
        def fn():
            ensure_folders()
            store = Store(self.world)
            try:
                dest = EXPORTS / f"nwn-gps-{store.path.stem}-{time.strftime('%Y-%m-%d_%H%M')}.sqlite"
                store.export(dest)
                st = store.stats()
            finally:
                store.close()
            self.notify(f"Map exported ({st['areas']} areas) to {short(dest)}", "ok")
        self._run("Export", fn)

    def import_inbox(self):
        def fn():
            ensure_folders()
            files = inbox_files()
            if not files:
                self.notify(f"No maps to import. Put friends' .sqlite files in {short(INBOX)}", "warn")
                return
            self.notify(f"Merging {len(files)} map{'s' if len(files) > 1 else ''}...", "info")
            store = Store(self.world)
            total = {"areas": 0, "pois": 0, "transitions": 0, "tile_layouts": 0}
            bad = []
            try:
                store.backup("before-import")
                for f in files:
                    try:
                        added = store.merge(f)
                    except Exception:
                        bad.append(f.name)
                        continue
                    for k in total:
                        total[k] += added.get(k, 0)
                    target = MERGED / f.name
                    if target.exists():
                        target = MERGED / f"{f.stem}-{time.strftime('%Y%m%d%H%M%S')}{f.suffix}"
                    shutil.move(str(f), str(target))
            finally:
                store.close()
            msg = (f"Imported: +{total['areas']} areas, +{total['pois']} places, "
                   f"+{total['transitions']} routes, +{total['tile_layouts']} maps")
            if bad:
                msg += f". Not a GPS map: {', '.join(bad)[:60]}"
            self.notify(msg, "ok" if not bad else "warn")
        self._run("Import", fn)
