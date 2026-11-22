"""In-game text HUD through RivaTuner Statistics Server (works in exclusive fullscreen).

  python -m nwngps.hud ["<destination>"]
  python -m nwngps.cli go "<destination>"     change destination while the HUD runs
  python -m nwngps.cli go --stop              clear it

Needs RTSS running with its on-screen display enabled. Ctrl+C to stop (the HUD
removes its text from the game when it exits).
"""
import json
import sys
import time
from pathlib import Path

from .db import DATA_DIR, Store
from .nav import Navigator, compass
from .rtss import RTSS
from .session import IN_GAME, Session

TARGET_FILE = DATA_DIR / "nav_target.json"
GREEN, WHITE, GREY, GOLD = "4CD964", "FFFFFF", "9AA5AE", "F2C94C"


def set_target(text, pick=None):
    """Write (or clear) the shared destination. `pick` = exact row chosen in the picker."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if text or pick:
        TARGET_FILE.write_text(json.dumps({"query": text or pick["name"], "pick": pick, "t": time.time()}))
    elif TARGET_FILE.exists():
        TARGET_FILE.unlink()


def read_target():
    """The current destination record ({"query", "pick", "t"}) or None."""
    try:
        return json.loads(TARGET_FILE.read_text())
    except (OSError, ValueError):
        return None


def resolve_target(store, target):
    """Destination row for the Navigator: the exact pick if there is one, else the best search hit."""
    if not target:
        return None
    if target.get("pick"):
        return target["pick"]
    hits = store.search(target.get("query", ""))
    return dict(hits[0]) if hits else None


def turn_glyph(rel):
    if rel is None:
        return "  "
    i = int(((rel + 360) % 360 + 22.5) // 45) % 8
    return ["^^", "^>", ">>", "v>", "vv", "<v", "<<", "<^"][i]


def c(color, text):
    return f"<C={color}>{text}<C>"


def render(g, snap):
    if g is None:
        return c(GREY, f"GPS  {snap.area_name or ''}") if snap.state == IN_GAME else ""
    head = c(WHITE, f"GPS -> {g.dest_name[:40]}")
    if g.status == "NAV":
        rel = g.relative
        turn = ("ahead" if rel is not None and abs(rel) < 20 else
                "behind" if rel is not None and abs(rel) > 160 else
                f"{'right' if (rel or 0) > 0 else 'left'} {abs(rel or 0):.0f}" + chr(176))
        body = f"{c(GREEN, turn_glyph(rel) + f' {g.distance:.0f} m')}  {c(GREY, compass(g.bearing) + ' ' + turn)}"
        lines = [head, body, c(WHITE, g.line1)]
        if g.line2:
            lines.append(c(GREY, g.line2))
    elif g.status == "ARRIVED":
        lines = [head, c(GREEN, g.line1)]
    elif g.status == "NO_ROUTE":
        lines = [head, c(GOLD, g.line1), c(GREY, g.line2)]
    else:
        lines = [head, c(GREY, g.line1)]
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1:
        set_target(" ".join(sys.argv[1:]))
    store, session, osd = Store(), Session(log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)), RTSS()
    nav, query, warned = None, None, False
    print("HUD running (Ctrl+C to stop)")
    try:
        while True:
            q = read_target()
            if q != query:
                query = q
                dest = resolve_target(store, q)
                nav = Navigator(store, dest) if dest else None
                if dest:
                    print(f"destination: {dest['name']} in {store.area_name(dest['area'])}")
            snap = session.poll()
            text = render(nav.update(snap) if nav else None, snap)
            if not osd.show(text) and not warned:
                print("RTSS not running (or OSD unavailable): start RivaTuner Statistics Server")
                warned = True
            elif warned and osd.view:
                print("RTSS connected")
                warned = False
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        osd.close()
        session.close()
        store.close()
        print("HUD stopped")


if __name__ == "__main__":
    main()
