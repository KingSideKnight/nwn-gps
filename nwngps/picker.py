"""Destination picker driven by key events from the in-game DLL.

Empty query: "Clear destination" and the two "Save ..." rows when they apply, then your saved
places, then recent destinations. Typing searches saved places, areas, pins and doors.
Up/Down/PgUp/PgDn (or the mouse wheel) move, Enter or a click picks, Esc cancels. With nothing typed, Delete twice on a saved
place removes it. Picking a "Save ..." row asks for a name (Enter keeps the suggestion, Esc goes back).
"""
import json

from .db import DATA_DIR, MAX_PLACE_NAME, PLACE

VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE = 0x08, 0x09, 0x0D, 0x1B
VK_PRIOR, VK_NEXT, VK_END, VK_HOME, VK_UP, VK_DOWN, VK_DELETE = 0x21, 0x22, 0x23, 0x24, 0x26, 0x28, 0x2E
(EV_TOGGLE, EV_OPEN, EV_CHAR, EV_KEY, EV_CLEAR, EV_MOVED, EV_FULLMAP, EV_EXPORT, EV_IMPORT, EV_LABELS,
 EV_MAPKEY, EV_MAPCLICK, EV_WINDOW, EV_PICKCLICK) = range(1, 15)
RECENT_FILE = DATA_DIR / "recent.json"
MAX_RESULTS, MAX_RECENT, MAX_LIST = 12, 10, 60
PAGE = 5                                 # rows PgUp / PgDn move by
CLEAR = {"kind": "clear", "name": "Clear destination", "area": None, "x": None, "y": None}


def pick_dict(row):
    out = {k: row[k] for k in ("kind", "area", "name", "x", "y")}
    if row["kind"] == PLACE:
        out["id"] = row["id"]
    return out


def load_recent():
    try:
        return json.loads(RECENT_FILE.read_text())[:MAX_RECENT]
    except (OSError, ValueError):
        return []


def remember(pick):
    rec = [r for r in load_recent() if (r["area"], r["name"]) != (pick["area"], pick["name"])]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps([pick] + rec[:MAX_RECENT - 1]))


def plain_name(name):
    """A destination's name without the " [tag]" search adds to doors."""
    name = name or ""
    return name[:name.rindex(" [")] if name.endswith("]") and " [" in name else name


class Picker:
    def __init__(self, store):
        self.store = store
        self.open = False
        self.query, self.sel, self.results = "", 0, []
        self.has_destination = False
        self.dest, self.here = None, None
        self.naming = None               # the place being named: {"area", "x", "y", "z", "suggest"}
        self.confirm = None              # id of the saved place a first Delete asked about

    # --- the list ----------------------------------------------------------
    def _save_rows(self):
        rows = []
        d = self.dest
        if d and d.get("kind") not in (PLACE, "area") and d.get("x") is not None and d.get("area"):
            rows.append({"kind": "save_dest", "name": "Save current destination", "area": d["area"],
                         "x": d["x"], "y": d["y"], "suggest": plain_name(d.get("name"))})
        h = self.here
        if h and h.get("area") and h.get("x") is not None:
            rows.append({"kind": "save_here", "name": "Save where I'm standing", "area": h["area"],
                         "x": h["x"], "y": h["y"], "z": h.get("z", 0.0), "suggest": h.get("suggest") or ""})
        return rows

    def _refresh(self):
        if self.naming:
            self.results = []
        elif self.query.strip():
            self.results = [pick_dict(r) for r in self.store.search(self.query.strip(), limit=MAX_RESULTS)]
            self.results = self.results[:MAX_RESULTS]
        else:
            saved = [pick_dict(r) for r in self.store.saved_places()]
            have = {(r["area"], r["name"]) for r in saved}
            recent = [r for r in load_recent() if r.get("kind") != PLACE and (r["area"], r["name"]) not in have]
            self.results = (([CLEAR] if self.has_destination else []) + self._save_rows() + saved + recent)[:MAX_LIST]
        self.sel = min(self.sel, max(0, len(self.results) - 1))

    def start(self, has_destination, dest=None, here=None):
        """dest: the current destination (a pick dict) if any; here: where you stand,
        {"area", "x", "y", "z", "suggest"} (suggest = a name for the spot) or None."""
        self.open, self.query, self.sel = True, "", 0
        self.has_destination, self.dest, self.here = has_destination, dest, here
        self.naming, self.confirm = None, None
        self._refresh()

    def selected(self):
        return self.results[self.sel] if self.results else None

    # --- keys ---------------------------------------------------------------
    def _name_key(self, ev_type, code):
        if ev_type == EV_CHAR:
            if len(self.query) < MAX_PLACE_NAME:
                self.query += chr(code)
        elif code == VK_ESCAPE:                      # back to the list, nothing saved
            self.naming, self.query = None, ""
            self._refresh()
        elif code == VK_RETURN:
            n = self.naming
            name = " ".join(self.query.split()) or n["suggest"] or self.store.area_name(n["area"])
            self.open, self.naming = False, None
            return ("save", {"area": n["area"], "x": n["x"], "y": n["y"], "z": n.get("z") or 0.0, "name": name})
        elif code in (VK_BACK, VK_DELETE):
            self.query = self.query[:-1]
        return None

    def handle(self, ev_type, code):
        """Returns ("pick", dict) | ("clear", None) | ("cancel", None) | ("save", place) |
        ("remove", saved place dict) | None. After "remove", call removed() once it's done."""
        if not self.open:
            return None
        if self.naming:
            return self._name_key(ev_type, code)
        confirm, self.confirm = self.confirm, None   # any other key forgets a first Delete
        if ev_type == EV_CHAR:
            self.query += chr(code)
            self.sel = 0
            self._refresh()
        elif ev_type == EV_KEY:
            if code == VK_ESCAPE:
                self.open = False
                return ("cancel", None)
            if code == VK_RETURN:
                choice = self.selected()
                if choice is None:
                    self.open = False
                    return ("cancel", None)
                if choice["kind"] in ("save_here", "save_dest"):
                    self.naming = {k: choice.get(k) for k in ("area", "x", "y", "z", "suggest")}
                    self.query = ""
                    self._refresh()
                    return None
                self.open = False
                if choice["kind"] == "clear":
                    return ("clear", None)
                remember(choice)
                return ("pick", choice)
            choice = self.selected()
            if code == VK_DELETE and not self.query and choice and choice["kind"] == PLACE:
                if confirm == choice["id"]:
                    return ("remove", choice)
                self.confirm = choice["id"]
            elif code in (VK_BACK, VK_DELETE):
                self.query = self.query[:-1]
                self.sel = 0
                self._refresh()
            elif code in (VK_DOWN, VK_TAB):
                self.sel = min(self.sel + 1, len(self.results) - 1) if self.results else 0
            elif code == VK_UP:
                self.sel = max(self.sel - 1, 0)
            elif code == VK_NEXT:
                self.sel = min(self.sel + PAGE, max(0, len(self.results) - 1))
            elif code == VK_PRIOR:
                self.sel = max(self.sel - PAGE, 0)
            elif code == VK_END:
                self.sel = max(0, len(self.results) - 1)
            elif code == VK_HOME:
                self.sel = 0
        return None

    def click(self, index):
        """A click on result row `index`: the same as selecting it and pressing Enter. Clicks while
        naming a place, or that miss every row, do nothing (None)."""
        if not self.open or self.naming or index is None or not 0 <= index < len(self.results):
            return None
        self.sel = index
        return self.handle(EV_KEY, VK_RETURN)

    def removed(self):
        """The saved place "remove" returned is gone: update the list."""
        self._refresh()
