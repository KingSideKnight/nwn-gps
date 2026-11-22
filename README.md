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

Settings: `Documents\NWN GPS\settings.json`. Data: `Documents\NWN GPS\data`, logs:
`Documents\NWN GPS\logs` (set `NWNGPS_DATA` to override the data folder). The in-game DLL is loaded
from `<app folder>\runtime`, falling back to `Documents\NWN GPS\runtime`.

Why not AppData: processes started from a packaged (MSIX) Windows app, such as a terminal inside one,
get AppData silently redirected to a private per-app copy. Data, logs and the DLL written there are
invisible to the same tool started from Explorer, and to the game. `pip install --user` is affected
the same way, so install Pillow system-wide or use the packaged exe.

Scale (synthetic, `recon/scale_test.py`): 3,888 areas, 145,800 POIs, 9,558 transitions = 26 MB;
search 4 ms, whole-world route 76 ms, full-screen map frame 73 ms.

## Layout
- `nwngps/` application (`__main__.py` entry point, `config.py` paths/settings)
- `native/` the in-game DLL (C, ~600 lines, no third-party code)
- `tests/` unit tests; `recon/` reverse-engineering tools and notes (`recon/FINDINGS.md`)

## Security
See [SECURITY.md](SECURITY.md) for the trust model, attack surfaces and protections
(`tests/test_security.py` covers hostile map files, server content limits and DLL integrity).

## License
MIT (see `LICENSE`). Bundled third-party components: `THIRD_PARTY_NOTICES.txt`.
Build a release with `python packaging/build_release.py` (needs PyInstaller).

## Supported game build
Neverwinter Nights: Enhanced Edition 8193.37-17 (26c6e573, Oct 2025). Other builds are detected
and refused until `layout.py` is updated (re-run `recon/find_vtables.py` and the probes).
