"""NWN GPS entry point (also the packaged NWN-GPS.exe).

  NWN-GPS                    start everything (recorder + in-game GPS)
  NWN-GPS recorder           only record the map
  NWN-GPS ingame [dest]      only the in-game panel
  NWN-GPS settings           the Settings window (also: press S in the NWN GPS window)
  NWN-GPS cli <command> ...  search, routes, export/merge, world map (see `NWN-GPS cli`)
  NWN-GPS overlay | hud      desktop-window / RivaTuner alternatives to the in-game panel
"""
import sys

PARTS = {"recorder": "nwngps.recorder", "ingame": "nwngps.ingame", "cli": "nwngps.cli",
         "overlay": "nwngps.overlay", "hud": "nwngps.hud", "launcher": "nwngps.launcher",
         "settings": "nwngps.settings_window"}


def main():
    part = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in PARTS else "launcher"
    if any(a in ("-h", "--help", "/?") for a in sys.argv[1:]):
        import importlib
        print(importlib.import_module(PARTS[part]).__doc__ if part != "launcher" else __doc__)
        return
    if part != "launcher" or (len(sys.argv) > 1 and sys.argv[1] == "launcher"):
        sys.argv = [f"nwngps {part}"] + sys.argv[2:]
    from .db import migrate_legacy
    migrate_legacy()
    import importlib
    import runpy
    if part == "recorder":
        from .single import single_instance
        single_instance("recorder")
        importlib.import_module("nwngps.recorder").Recorder().run()
    else:
        mod = importlib.import_module(PARTS[part])
        if hasattr(mod, "main"):
            mod.main()
        else:
            runpy.run_module(PARTS[part], run_name="__main__")


def guarded_main():
    """Run main(); if a part crashes, write the error where the player (and support) can find it."""
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import time
        import traceback
        try:
            from .config import LOG_DIR
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            part = sys.argv[0].split()[-1] if sys.argv and " " in sys.argv[0] else "launcher"
            with open(LOG_DIR / f"crash-{part}.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} argv={sys.argv} cwd={__import__('os').getcwd()}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    guarded_main()
