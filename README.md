# NWN GPS

A GPS for Neverwinter Nights: Enhanced Edition multiplayer servers: records the world as you play,
searches places, routes across areas and linked servers, and draws an in-game panel (works in
exclusive fullscreen). **Players: see [USER_GUIDE.md](USER_GUIDE.md).** This file is for developers.

## How it works
- **Reading:** `nwngps/session.py` reads `nwmain.exe` memory with read-only access (area, position,
  pins, doors, tiles). Offsets live in `nwngps/layout.py`; `session.check_layout` verifies every
  class vtable via RTTI at attach and refuses unknown game builds.
- **Recording:** `nwngps/recorder.py` -> SQLite per world (`db.py`), including portals between
  linked servers.
- **Drawing in-game:** `native/nwngps_gl.c` is loaded into the game at runtime; it swaps
  `GDI32!SwapBuffers` in nwmain's import table, draws a texture Python publishes through shared
  memory, reads hotkeys via a window subclass, and unhooks/unloads on request. No game files change.
- **Maps:** tile layouts from memory + tileset art from NWSync / texture packs / KEY-BIF
  (`resources.py`, `maps.py`, `worldmap.py`).

## Run from source
    native\build.cmd                  # once (Visual Studio 2022 C++ tools)
    python -m pip install pillow
    python -m nwngps                  # launcher: recorder + in-game GPS (or start_gps.cmd)
    python -m nwngps cli --help       # search, routes, export/merge, world map
    python -m unittest discover -s tests

Settings: `Documents\NWN GPS\settings.json`. Data: `%LOCALAPPDATA%\NWN GPS` (set `NWNGPS_DATA` to
override). The in-game DLL is loaded from `<app folder>\runtime` (some systems block DLLs loaded
from AppData).

Scale (synthetic, `recon/scale_test.py`): 3,888 areas, 145,800 POIs, 9,558 transitions = 26 MB;
search 4 ms, whole-world route 76 ms, full-screen map frame 73 ms.

## Layout
- `nwngps/` application (`__main__.py` entry point, `config.py` paths/settings)
- `native/` the in-game DLL (C, ~600 lines, no third-party code)
- `tests/` unit tests; `recon/` reverse-engineering tools and notes (`recon/FINDINGS.md`)

## Supported game build
Neverwinter Nights: Enhanced Edition 8193.37-17 (26c6e573, Oct 2025). Other builds are detected
and refused until `layout.py` is updated (re-run `recon/find_vtables.py` and the probes).
