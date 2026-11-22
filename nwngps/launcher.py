"""Start everything: the recorder and the in-game GPS, in one window.

  NWN-GPS.exe  /  python -m nwngps  /  start_gps.cmd

Both wait for the game, so you can start this before or after NWN. A part that
crashes is restarted after a few seconds. Ctrl+C (or closing the window) stops
both; on Ctrl+C the in-game GPS unloads its DLL from the game first.
Logs: %LOCALAPPDATA%\\NWN GPS\\logs.
"""
import subprocess
import sys
import time

from . import config

PARTS = {"recorder": "recorder", "in-game GPS": "ingame"}
RESTART_DELAY = 5.0

NOTICE = """
=====================================================================
 NWN GPS - please read once
=====================================================================
 * NWN GPS reads the game's memory to see where you are, and loads a
   small add-on into the running game to draw its panel. It never
   changes game files, saves or characters, and stops cleanly when
   you close it.
 * Some servers' rules restrict third-party tools that read or modify
   the game client. Check your server's rules before you use it.
   You use it at your own risk.
 * Start the game normally (not "as administrator").
 * Settings:  {settings}
 * Maps to share / receive:  {share}
=====================================================================
"""


def command(part):
    if config.frozen():
        return [sys.executable, part]
    return [sys.executable, "-u", "-m", "nwngps", part]


def start(part):
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(config.LOG_DIR / f"{part}.log", "a", encoding="utf-8")
    log.write(f"\n===== started by launcher {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    log.flush()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if config.frozen() else 0
    return subprocess.Popen(command(part), stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def first_run_notice():
    s = config.load_settings()
    if s.get("accepted_notice"):
        return True
    print(NOTICE.format(settings=config.SETTINGS_FILE, share=config.SHARE_DIR))
    try:
        answer = input(" Type YES to continue (anything else quits): ").strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        print(" Not started.")
        return False
    s["accepted_notice"] = True
    config.save_settings(s)
    return True


def main():
    from .single import single_instance
    single_instance("launcher")
    if not first_run_notice():
        return
    game = config.game_dir()
    print("NWN GPS: starting the map recorder and the in-game GPS. Leave this window open; Ctrl+C stops both.")
    print(f"  game: {game or 'not found yet (it will be picked up when you start the game)'}")
    print(f"  logs: {config.LOG_DIR}")
    from . import hotkeys
    hk = hotkeys.resolve(config.load_settings()["hotkeys"], warn=lambda m: print("  " + m))
    print("  in game: " + ", ".join(f"{v[2]} {hotkeys.LABELS[a].lower()}" for a, v in hk.items()))
    procs = {name: start(part) for name, part in PARTS.items()}
    died_at = {}
    try:
        while True:
            for name, part in PARTS.items():
                p = procs[name]
                if p.poll() is not None:
                    died_at.setdefault(name, time.time())
                    if time.time() - died_at[name] >= RESTART_DELAY:
                        print(time.strftime("%H:%M:%S"), f"{name} stopped (code {p.returncode}); restarting. "
                              f"Details: {config.LOG_DIR / (part + '.log')}")
                        procs[name] = start(part)
                        died_at.pop(name)
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        for name, p in procs.items():
            if p.poll() is None:
                try:
                    p.wait(timeout=8)     # children got the same Ctrl+C and clean up (DLL unload)
                except subprocess.TimeoutExpired:
                    p.kill()              # the DLL hides its panel by itself 3 s after updates stop
            print(f"{name} stopped")


if __name__ == "__main__":
    main()
