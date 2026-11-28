"""Map sharing for players: easy folders and background export / import.

  Documents\\NWN GPS\\Exports   your exported maps (Ctrl+Shift+E), send these to friends
  Documents\\NWN GPS\\Inbox     drop friends' maps here, then Ctrl+Shift+I merges them
  Documents\\NWN GPS\\Inbox\\merged   files that were merged (kept, never deleted)

Your own database is backed up before every import (data/backups). Each file is merged all or
nothing, the same file is never merged twice, and any one of them can be taken out again later
(Settings > Imported maps, or `cli imports` / `cli undo-import <id>`).
"""
import shutil
import threading
import time
from pathlib import Path

from .db import AlreadyImported, OtherWorld, Store


from .config import SHARE_DIR, documents_dir
EXPORTS, INBOX = SHARE_DIR / "Exports", SHARE_DIR / "Inbox"
MERGED = INBOX / "merged"


def ensure_folders():
    for d in (EXPORTS, INBOX, MERGED):
        d.mkdir(parents=True, exist_ok=True)


def inbox_files():
    return sorted(p for p in INBOX.glob("*.sqlite") if p.is_file()) if INBOX.exists() else []


def _to_merged(f):
    target = MERGED / f.name
    if target.exists():
        target = MERGED / f"{f.stem}-{time.strftime('%Y%m%d%H%M%S')}{f.suffix}"
    shutil.move(str(f), str(target))


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
                from . import config
                keep = bool(config.load_settings().get("share_places"))
                store.export(dest, share=True, keep_places=keep)   # no play times in files you send to others
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
            total = {"areas": 0, "pois": 0, "transitions": 0, "tile_layouts": 0, "places_skipped": 0}
            bad, elsewhere, again, done = [], [], [], 0
            try:
                store.backup("before-import")
                for f in files:
                    try:
                        added = store.merge(f)    # all or nothing: a failure leaves your map as it was
                    except OtherWorld as e:       # left in the Inbox for when you're on that server
                        elsewhere.append(f"{f.name} ({e.world})")
                        continue
                    except AlreadyImported:       # the same file again: nothing to add
                        again.append(f.name)
                        _to_merged(f)
                        continue
                    except Exception:
                        bad.append(f.name)
                        continue
                    done += 1
                    for k in total:
                        total[k] += added.get(k, 0)
                    _to_merged(f)
            finally:
                store.close()
            msg = (f"Imported: +{total['areas']} areas, +{total['pois']} places, "
                   f"+{total['transitions']} routes, +{total['tile_layouts']} maps")
            if total["places_skipped"]:
                n = total["places_skipped"]
                msg += f". Their {n} saved place{'s' if n > 1 else ''} not added (yours stay yours)"
            if done:
                msg += ". Undo: Settings > Imported maps"
            if again:
                msg += f". Already imported before: {', '.join(again)[:60]}"
            if elsewhere:
                msg += f". Another server's map, not imported: {', '.join(elsewhere)[:80]}"
            if bad:
                msg += f". Not a GPS map: {', '.join(bad)[:60]}"
            self.notify(msg, "ok" if not (bad or elsewhere) else "warn")
        self._run("Import", fn)
