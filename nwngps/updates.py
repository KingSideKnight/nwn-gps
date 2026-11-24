"""Update check: is a newer NWN GPS release out?

At most once a day (and only if "check_updates" is on in settings.json), the launcher asks
GitHub's public API for the project's release list. That request is all it sends: GitHub sees your
IP address and a "NWN-GPS/<version>" user agent, nothing about you, your game or your maps.
Nothing is ever downloaded or installed: you're told a newer version exists and where to get it.

The answer is kept in Documents\\NWN GPS\\data\\update.json, so the in-game GPS (another process)
can show the same news once per session without asking GitHub again.
"""
import json
import re
import ssl
import time
import urllib.request

from . import __version__
from .config import DATA_DIR

REPO = "KingSideKnight/nwn-gps"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES = f"https://github.com/{REPO}/releases"
STATE_FILE = DATA_DIR / "update.json"
CHECK_EVERY = 24 * 3600.0
TIMEOUT = 8.0
MAX_BYTES = 2_000_000
TAG = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})")


def parse_version(text):
    """'v0.1.5' / '0.1.5' -> (0, 1, 5); None for anything else."""
    m = TAG.fullmatch((text or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def release_url(version):
    """Built here, never taken from the response: the link we show always points at this project."""
    return f"{RELEASES}/tag/v{version}"


def newest(releases):
    """Highest published (non-draft) release version in GitHub's release list, or None.
    Pre-releases count: every NWN GPS release so far is one."""
    best = None
    for r in releases if isinstance(releases, list) else []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        v = parse_version(r.get("tag_name") if isinstance(r.get("tag_name"), str) else None)
        if v and (best is None or v > best):
            best = v
    return best


def fetch(timeout=TIMEOUT):
    """Ask GitHub for the newest release version. Raises on network or format trouble."""
    req = urllib.request.Request(API, headers={"User-Agent": f"NWN-GPS/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()            # verifies GitHub's certificate (Windows' store)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("release list too large")
    return newest(json.loads(body.decode("utf-8")))


def load_state():
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(s):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s), encoding="utf-8")


def available(state=None, current=None):
    """(version text, url) if the last check found a release newer than this one, else None."""
    s = load_state() if state is None else state
    latest, mine = parse_version(s.get("latest")), parse_version(current or __version__)
    if latest and mine and latest > mine:
        text = ".".join(map(str, latest))
        return text, release_url(text)
    return None


def check(settings, now=None, fetcher=fetch, force=False):
    """Check GitHub if the setting is on and the last check is a day old. Returns
    ("new", version, url) | ("current", None, None) | ("off" | "later" | "failed", None, None).
    force=True (the Settings window's "Check now") asks even if it's off or checked today."""
    if not force and not settings.get("check_updates", True):
        return "off", None, None
    now = time.time() if now is None else now
    s = load_state()
    last = s.get("checked") if isinstance(s.get("checked"), (int, float)) else None
    if not force and last is not None and 0 <= now - last < CHECK_EVERY:
        found = available(s)
        return ("new", *found) if found else ("later", None, None)
    try:
        latest = fetcher()
    except Exception:
        s["checked"] = now - CHECK_EVERY + 3600        # offline or GitHub down: try again in an hour
        save_state(s)
        return "failed", None, None
    s.update(checked=now, latest=".".join(map(str, latest)) if latest else s.get("latest"))
    save_state(s)
    found = available(s)
    return ("new", *found) if found else ("current", None, None)
