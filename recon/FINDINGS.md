# Recon findings

Game build: see `bin/win32/build.txt`. All RVAs below are for the build analysed on
2026-11-22; re-run `find_vtables.py` / `dump_exports.py` after every game patch.

## nwmain.exe (Windows, x64)
- PE32+, image base 0x140000000 (ASLR relocates; use module base + RVA).
- **18,245 named exports**, including engine globals, the server-side game
  classes (`CNWS*`) and networking. Client game classes (`CNWC*`) are mostly *not* exported.
- RTTI present for 804 classes: client classes are findable via vtables.

### Exported globals (RVA)
| name | RVA |
|---|---|
| g_pAppManager | 0x12df970 |
| g_pExoResMan | 0x12df960 |
| g_pGuiMan | 0x12df8b0 |
| g_pServerInfo | 0x12df8d0 |
| g_pRules | 0x12df8f8 |

### Client class vtables (RVA) – `vtables.json`
CNWCArea 0xe45a38, CNWCDoor 0xe52f68, CNWCTrigger 0xe533f8, CNWCMapPin 0xe72800,
CNWCCreature 0xe474e8, CNWCPlayer 0xe3dfb8, CNWCModule 0xe44d18, CNWCPlaceable 0xe53950,
CPanelAreaMap 0xe59210, CGuiMapPin 0xe4f978, CGuiMapSurface 0xe59108, CGuiAreaLoadscreen 0xe4c0a8.

## Network
- Client<->server traffic is **encrypted** (libhydrogen `hydro_kx_xx` key exchange,
  per-connection session keys; `Documents\Neverwinter Nights\cryptographic_secret` is the client identity).
  Passive packet capture is useless on its own.
- Decrypted/decompressed messages pass through the exported
  `CNetLayerInternal::UncompressMessage(uint, uchar*, uint)` (RVA in exports dump) – a future
  in-process hook point if memory reading isn't enough.
- Message *formats* can be learned from the exported server-side writers
  `CNWSMessage::SendServerToPlayer*` (same binary).

## Live findings (2026-11-22, Arelith, build 26c6e573 Oct 6 2025)
Field offsets live in `nwngps/layout.py`; `python -m nwngps.snapshot` prints current state.
- The game must NOT run as administrator (a normal-user process can't read an elevated one).
- Client holds exactly one CNWCArea (the current area). Seen: 1 area, 1 creature, 7 doors,
  2 map pins, 154 placeables, 0 triggers.
- CNWCObject header: +0x08 object id, +0x30 CNWCArea*, +0x38 position xyz, +0x44 facing xyz.
- CNWCArea: +0x118 id, +0x128 resref (char[16]), +0x150 tileset resref, +0x238 name (char*),
  width/height in tiles at +0x0C/+0x10. (An early guess of +0x2A0/+0x2A4 was wrong: that's the
  size of a 10-entry list; it read 10x10 for every area.) Tile array: +0x298, CNWTile stride 0x60.
- CNWCMapPin: +0x178 text. Arelith puts pins at transitions ("Northern Outskirts").
- CNWCDoor: +0x170 name (e.g. "The Vineyard Nymph"), +0x1C8 tag; door objects are 0x1E0 apart.
- CNWCModule: +0x18 name "Arelith", +0xB0 NWSync URL.
- Network traffic is unusable without hooks (see above).

### Pointer chains (verified across 2 area transitions)
- current area: `*g_pAppManager -> +0x0 (CClientExoApp) -> +0x8 (internal) -> +0x30 (CNWCModule) -> +0xF8 (CNWCArea)`
- player creature: `... internal -> +0x640 (unknown holder) -> +0xE8 (CNWCCreature)`; position verified by walking.
- `python -m nwngps.live --log file.jsonl` records area_change events (exit pos in old area,
  entry pos in new). First edge: ir_coroutskwllhs (54.91,11.83) <-> cordortradehaus (54.98,33.79);
  the exit matched the "Mercantile Building" map pin (54.83,11.59) on the upper floor.

### After a relog (same game process)
- Area chain (module +0xF8) still works; the CNWCModule object is recreated.
- The `internal+0x640 -> +0xE8` player chain broke (slot moved to +0x6E8). Replaced by:
  player id at `internal+0x48` (also `module+0x124`), value 0xFFFFFFF6 both sessions,
  resolved through the object table.
- The object table moved (0x...a3040 -> 0x...a8040); validate it by resolving the area's ids (>=80%).
  A first locate accepted a look-alike table that resolved only 1 id; validation fixed that.
- Menu / character select: module present but name empty, area pointer 0, old creature freed.

### Server identity
- CNWCModule +0xB0 NWSync URL (http://nwsync.nwnarelith.com) is shared by all Arelith servers -> "world".
- CNWCModule +0xD8 e.g. "ARE_CitiesAndPlanes" -> server within the world.
- Connection address strings (game.arelith.com:5121, 207.246.92.7:5121) are in heap memory too.
- The client internal object also holds the account name and CD key: never log or store those.

## Open questions
- [x] Confirm the CNWCCreature found is the player (position changes when you walk)
- [ ] Pointer path from the area to its object list (doors, pins, placeables) so we don't need scans
- [ ] Area width/height confirmation + tile list (pointer near +0x298)
- [ ] Doors/triggers: transition flag + destination (likely server-only; learn by observing area changes)
- [ ] Stable path from g_pAppManager to current area / player (so no full-memory scan each time)
- [ ] DM client: is there a "this is a DM" flag (CNWCPlayer / client internal)? Then `dm_mode` can be
      automatic. Also: does the player id at internal+0x48 follow a possessed creature?
- [ ] Creature current / max HP on CNWCCreature: lets the recorder spot deaths on servers without a
      death area (graveyard respawns) instead of relying on the teleport rule.
- [ ] Arelith's Fugue: confirm the area name contains "Fugue" (the `death_areas` default).
