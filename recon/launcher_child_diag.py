"""Start a part exactly as the launcher does, but capture its output. Usage: python launcher_child_diag.py recorder"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nwngps import config, launcher  # noqa: E402

part = sys.argv[1] if len(sys.argv) > 1 else "recorder"
cmd = launcher.command(part)
print("cmd:", cmd, "\ncwd:", Path.cwd(), "\nlog dir:", config.LOG_DIR, config.LOG_DIR.exists())
try:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    print("exit", p.returncode, "\nstdout:", p.stdout[-1500:], "\nstderr:", p.stderr[-1500:])
except subprocess.TimeoutExpired as e:
    print("still running after 8 s (ok):", (e.stdout or b"")[-500:])
