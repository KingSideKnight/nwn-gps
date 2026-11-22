"""Print the live game state a few times a second (debug view).

  python -m nwngps.live [--seconds N]
"""
import sys
import time

from .session import Session


def main():
    dur = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else None
    s = Session()
    start, lastline = time.time(), None
    try:
        while dur is None or time.time() - start < dur:
            snap = s.poll()
            line = f"{snap.state:8} {snap.server} {snap.area} {snap.pos} facing={snap.facing}"
            if line != lastline:
                print(line, flush=True)
                lastline = line
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        s.close()


if __name__ == "__main__":
    main()
