# Security notes

NWN GPS reads the game's memory and loads a small DLL into the running game, so it is careful
about every way outside data can reach it. This file lists those ways and what protects them.

## Trust model
- **You** (programs running as your Windows user) are trusted. Any such program could already read
  or modify the game, so NWN GPS doesn't try to defend against them.
- **Map files from other players** (Inbox / `cli merge`) are **untrusted**.
- **Server content** (NWSync files: tilesets, textures) is **untrusted**. A server shouldn't be able
  to hurt a player's PC through NWN GPS.
- **The game's memory** is treated as possibly inconsistent (loads, patches): every read is bounded.

## Attack surfaces and protections
| Surface | Protection |
|---|---|
| Imported map databases | Max 512 MB; must be an SQLite file with real `areas`/`pois`/`transitions` **tables** (views refused); opened read-only in SQLite defensive mode with untrusted schema; `quick_check` must pass; row limits per table; every value validated (resref format, string lengths, finite coordinates within 0-690 m, area sizes 1-64 tiles, tile lists exactly w*h with valid ids/orientations). Invalid rows are skipped and reported as "rejected". Your database is backed up before every import. Each file is merged in one transaction (a failure leaves nothing behind), the same file (SHA-256) is never merged twice, each map counts once per link (so re-sending files can't make an untrusted teleport routable), and every import can be undone (`undo_import`). |
| NWSync blobs (server content) | Declared size max 64 MB; zstd output capped to the declared size; mismatches are treated as missing. |
| Textures and tileset files | Image dimensions checked from the header before decoding (max 1024 px per side); Pillow's pixel limit set to 16 M; `.set` files max 16 MB; area maps max 64x64 tiles. |
| The DLL loaded into the game | Loaded from the program folder or `Documents\NWN GPS\runtime`, never from AppData; an existing copy is used only if its bytes match the bundled DLL (SHA-256), otherwise it is replaced or that folder is skipped. Loaded by absolute path. |
| Shared memory (panel image, hotkeys, key events) | Same-user only (lower-integrity processes can't write it). The DLL bounds-checks every value it reads (frame size, anchor, event index, hotkey table); Python caps frame sizes it renders. |
| Game memory reads | Read-only process handle for reading; fixed maximum lengths for every string, list and tile array; game builds whose class layout doesn't match are refused (`UNSUPPORTED`). |
| Process access for injection | Only `CreateRemoteThread`/`VirtualAllocEx`/`WriteProcessMemory` to pass the DLL path to `LoadLibraryW`; nothing else is written into the game. |

## Privacy
- The only network request is the daily update check (`nwngps/updates.py`, on by default, off in
  Settings or with `"check_updates": false`): one HTTPS GET to `api.github.com` for this project's
  release list, with a `NWN-GPS/<version>` user agent. GitHub sees your IP address; nothing about
  you, your game or your maps is sent. Nothing is downloaded or installed, and the link shown is
  built from the version number, never taken from the response.
- Sharing maps only happens when you send a file yourself.
- Exported maps (`Ctrl+Shift+E`, `cli export`) have play times and visit counts removed, and the
  list of maps you imported. They carry a random 16-hex-digit id for your map (made with
  `secrets`, nothing derived from you or your PC) so a friend's GPS counts your map once per link;
  two of your exports can be told to come from the same map, nothing more.
- Logs contain areas, positions and hotkey/picker actions, never account names or CD keys.
  (Developer recon tools in `recon/` *can* print such values from memory; their output folder is
  git-ignored and they are not part of the release.)

## Known limits
- Map data from friends is trusted for routing once imported: a deliberately wrong map can give
  wrong directions. Only import maps from people you trust.
- The release is not code-signed yet.

## Reporting a problem
Open an issue on the repository, or contact the maintainer privately for anything sensitive.
