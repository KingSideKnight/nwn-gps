"""One controlled injection with diagnostics (exit code, module list, DLL status), then a clean unload."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import ingame  # noqa: E402
from nwngps.memory import find_pid  # noqa: E402

pid = find_pid()
shm = ingame.Shm()
print("flags before:", shm.flags(), "status:", shm.status())
dll = ingame.runtime_dll()
print("dll:", dll)
ok = ingame.inject(pid, dll)
print("inject() returned", ok)
time.sleep(1.5)
print("modules:", ingame.our_modules(pid))
print("status:", shm.status())
if ingame.our_modules(pid):
    print("unloading:", ingame.unload_old(pid, shm), ingame.our_modules(pid))
shm.close()
