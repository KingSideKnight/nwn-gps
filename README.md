# nwn-gps

Player-side GPS for Neverwinter Nights: Enhanced Edition (target: Arelith).
External companion app: reads the running game's memory (read-only), builds a
POI / area-transition database, routes between areas, and draws an overlay.

## Rollback guarantees
- Nothing in this project writes to the game install or `Documents\Neverwinter Nights`.
- Memory access opens `nwmain.exe` with `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION`
  only: the OS will refuse any write.
- Everything lives in this folder under git. To undo: `git log`, `git revert <commit>`,
  or delete the folder.
- If a future step must touch a game file, it backs the file up first and ships a restore script.

## Layout
- `nwngps/memory.py` – read-only process memory access (scan, read, strings).
- `recon/` – reverse-engineering tools and notes (`FINDINGS.md`).
  - `inspect_exe.py`, `dump_exports.py`, `find_vtables.py` – static analysis of nwmain.exe
  - `probe.py` – live read-only probing (`python recon/probe.py` for help)
  - `out/` – probe logs and dumps (git-ignored)
