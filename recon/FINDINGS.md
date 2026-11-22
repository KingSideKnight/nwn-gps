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
  +0x2A0/+0x2A4 probably width/height in tiles (10x10 seen; positions 0..100 m fit).
- CNWCMapPin: +0x178 text. Arelith puts pins at transitions ("Northern Outskirts").
- CNWCDoor: +0x170 name (e.g. "The Vineyard Nymph"), +0x1C8 tag; door objects are 0x1E0 apart.
- CNWCModule: +0x18 name "Arelith", +0xB0 NWSync URL.
- Network traffic is unusable without hooks (see above).

## Open questions
- [ ] Confirm the CNWCCreature found is the player (position changes when you walk)
- [ ] Area width/height confirmation + tile list (pointer near +0x298)
- [ ] Doors/triggers: transition flag + destination (likely server-only; learn by observing area changes)
- [ ] Stable path from g_pAppManager to current area / player (so no full-memory scan each time)
