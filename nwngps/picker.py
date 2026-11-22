"""Destination picker driven by key events from the in-game DLL.

Empty query: recent destinations (+ "Clear destination" when one is set).
Typing searches areas, pins and doors. Up/Down/PgUp/PgDn move, Enter picks, Esc cancels.
"""
import json

from .db import DATA_DIR

VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE = 0x08, 0x09, 0x0D, 0x1B
VK_PRIOR, VK_NEXT, VK_END, VK_HOME, VK_UP, VK_DOWN, VK_DELETE = 0x21, 0x22, 0x23, 0x24, 0x26, 0x28, 0x2E
EV_TOGGLE, EV_OPEN, EV_CHAR, EV_KEY, EV_CLEAR = 1, 2, 3, 4, 5
RECENT_FILE = DATA_DIR / "recent.json"
MAX_RESULTS, MAX_RECENT = 8, 10
CLEAR = {"kind": "clear", "name": "Clear destination", "area": None, "x": None, "y": None}


def pick_dict(row):
    return {k: row[k] for k in ("kind", "area", "name", "x", "y")}


def load_recent():
    try:
        return json.loads(RECENT_FILE.read_text())[:MAX_RECENT]
    except (OSError, ValueError):
        return []


def remember(pick):
    rec = [r for r in load_recent() if (r["area"], r["name"]) != (pick["area"], pick["name"])]
    DATA_DIR.mkdir(exist_ok=True)
    RECENT_FILE.write_text(json.dumps([pick] + rec[:MAX_RECENT - 1]))


class Picker:
    def __init__(self, store):
        self.store = store
        self.open = False
        self.query, self.sel, self.results = "", 0, []
        self.has_destination = False

    def _refresh(self):
        if self.query.strip():
            self.results = [pick_dict(r) for r in self.store.search(self.query.strip(), limit=MAX_RESULTS)]
            self.results = self.results[:MAX_RESULTS]
        else:
            self.results = load_recent()[:MAX_RESULTS - 1]
            if self.has_destination:
                self.results = [CLEAR] + self.results
        self.sel = min(self.sel, max(0, len(self.results) - 1))

    def start(self, has_destination):
        self.open, self.query, self.sel = True, "", 0
        self.has_destination = has_destination
        self._refresh()

    def handle(self, ev_type, code):
        """Returns ("pick", dict) | ("clear", None) | ("cancel", None) | None."""
        if not self.open:
            return None
        if ev_type == EV_CHAR:
            self.query += chr(code)
            self.sel = 0
            self._refresh()
        elif ev_type == EV_KEY:
            if code == VK_ESCAPE:
                self.open = False
                return ("cancel", None)
            if code == VK_RETURN:
                self.open = False
                if not self.results:
                    return ("cancel", None)
                choice = self.results[self.sel]
                if choice["kind"] == "clear":
                    return ("clear", None)
                remember(choice)
                return ("pick", choice)
            if code in (VK_BACK, VK_DELETE):
                self.query = self.query[:-1]
                self.sel = 0
                self._refresh()
            elif code in (VK_DOWN, VK_TAB):
                self.sel = min(self.sel + 1, len(self.results) - 1) if self.results else 0
            elif code == VK_UP:
                self.sel = max(self.sel - 1, 0)
            elif code in (VK_NEXT, VK_END):
                self.sel = max(0, len(self.results) - 1)
            elif code in (VK_PRIOR, VK_HOME):
                self.sel = 0
        return None
