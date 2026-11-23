"""Hotkeys from settings.json -> the DLL's table and the panel legend.

Format: modifiers and one key joined by '+', e.g. "Ctrl+Shift+F", "Alt+F5", "Ctrl+Alt+Q".
Keys: A-Z, 0-9, F1-F12. At least one modifier is required (so the game keeps its own keys).
"""
from .config import DEFAULT_HOTKEYS

ORDER = ["search", "clear", "map", "hide", "export", "import", "labels"]     # same order as the DLL's table
LABELS = {"search": "Search", "clear": "Clear", "map": "Map", "hide": "Hide",
          "export": "Export map", "import": "Import maps",
          "labels": "Pin names"}
MODS = {"shift": 1, "ctrl": 2, "control": 2, "alt": 4}
TABLE_OFFSET = 1280


def parse(text):
    """'Ctrl+Shift+F' -> (vk, mods) or raise ValueError."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"{text!r}: needs a modifier and a key, e.g. Ctrl+Shift+F")
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            raise ValueError(f"{text!r}: unknown modifier {p!r} (use Ctrl, Shift, Alt)")
        mods |= MODS[p]
    key = parts[-1].upper()
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return ord(key), mods
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return 0x70 + int(key[1:]) - 1, mods
    raise ValueError(f"{text!r}: unsupported key {parts[-1]!r} (use A-Z, 0-9, F1-F12)")


def resolve(settings_hotkeys, warn=print):
    """{action: (vk, mods, text)} with invalid or duplicate entries replaced by defaults."""
    out, seen = {}, {}
    for action in ORDER:
        text = (settings_hotkeys or {}).get(action) or DEFAULT_HOTKEYS[action]
        try:
            vk, mods = parse(text)
            if (vk, mods) in seen:
                raise ValueError(f"{text!r} is already used for {seen[(vk, mods)]}")
        except ValueError as e:
            warn(f"hotkey for {action}: {e}; using {DEFAULT_HOTKEYS[action]}")
            text = DEFAULT_HOTKEYS[action]
            vk, mods = parse(text)
        seen[(vk, mods)] = action
        out[action] = (vk, mods, "+".join(p.strip().capitalize() if len(p.strip()) > 1 else p.strip().upper()
                                          for p in text.split("+")))
    return out


def table_bytes(resolved):
    import struct
    return b"".join(struct.pack("<II", resolved[a][0], resolved[a][1]) for a in ORDER)


def legend_rows(resolved):
    """Rows for the panel legend: (prefix or None, [(key, label), ...]) x2."""
    def split(text):
        mods, _, key = text.rpartition("+")
        return mods, key
    rows = []
    for actions in (["search", "clear", "map", "hide"], ["export", "import"]):
        mods = {split(resolved[a][2])[0] for a in actions}
        if len(mods) == 1:
            rows.append((mods.pop(), [(split(resolved[a][2])[1], LABELS[a]) for a in actions]))
        else:
            rows.append((None, [(resolved[a][2], LABELS[a]) for a in actions]))
    return rows
