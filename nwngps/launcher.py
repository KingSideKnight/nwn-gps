"""Start everything: the recorder and the in-game GPS, in one window.

  python -m nwngps.launcher        (or double-click start_gps.cmd / the desktop shortcut)

Both wait for the game, so you can start this before or after NWN. A part that
crashes is restarted after a few seconds. Ctrl+C (or closing the window) stops
both; on Ctrl+C the in-game GPS unloads its DLL from the game first.
Logs: recon/out/recorder.log and recon/out/ingame.log.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "recon" / "out"
PARTS = {"recorder": "nwngps.recorder", "in-game GPS": "nwngps.ingame"}
RESTART_DELAY = 5.0


def start(module, logname):
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / logname, "a", encoding="utf-8")
    log.write(f"\n===== started by launcher {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    log.flush()
    return subprocess.Popen([sys.executable, "-u", "-m", module], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)


def main():
    from .single import single_instance
    single_instance("launcher")
    print("NWN GPS: starting recorder and in-game GPS (Ctrl+C to stop both)")
    print("In game: Ctrl+Shift+F search  Ctrl+Shift+X clear  Ctrl+Shift+G hide  Ctrl+Shift+M full map")
    procs = {name: start(mod, mod.split(".")[1] + ".log") for name, mod in PARTS.items()}
    died_at = {}
    try:
        while True:
            for name, mod in PARTS.items():
                p = procs[name]
                if p.poll() is not None:
                    died_at.setdefault(name, time.time())
                    if time.time() - died_at[name] >= RESTART_DELAY:
                        print(time.strftime("%H:%M:%S"), f"{name} exited (code {p.returncode}); restarting")
                        procs[name] = start(mod, mod.split(".")[1] + ".log")
                        died_at.pop(name)
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        for name, p in procs.items():
            if p.poll() is None:
                # children share this console and got the same Ctrl+C; give them time to clean up
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()      # the DLL hides its panel by itself 3 s after updates stop
            print(f"{name} stopped")


if __name__ == "__main__":
    main()
