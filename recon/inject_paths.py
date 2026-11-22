"""Which folders can the game load our DLL from? Copies the runtime DLL to test folders, injects,
records whether it loaded, unloads each time. Usage: python inject_paths.py"""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import ingame  # noqa: E402
from nwngps.memory import find_pid  # noqa: E402

src = ingame.runtime_dll()
la = Path(os.environ["LOCALAPPDATA"])
tests = [la / "nwngpstest" / "a.dll", la / "nwngps test" / "b.dll",
         Path.home() / "nwngpstest" / "c.dll", Path(r"D:\Projects\nwn-gps\data\runtime") / "d with space" / "d.dll"]
pid = find_pid()
shm = ingame.Shm()
for t in tests:
    t.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, t)
    ok = ingame.inject(pid, t)
    time.sleep(0.8)
    loaded = ingame.our_modules(pid) + [m for m in ingame.our_modules(pid)]
    print(f"{str(t):70} inject={ok}")
    if ok:
        ingame.unload_old(pid, shm)
shm.close()
print("still loaded:", ingame.our_modules(pid))
