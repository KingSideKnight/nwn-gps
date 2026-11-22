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

## Open questions (need the game running, logged in)
- [ ] CNWCArea fields: name, tag, resref, width/height, tileset, tile list
- [ ] Player creature: which CNWCCreature is us; position (x,y,z) & facing offsets
- [ ] Doors/triggers: transition flag + destination (probably server-only; may need to learn by observing area changes)
- [ ] Map pins: CNWCMapPin fields (text, position) and where the list lives
- [ ] Stable path from g_pAppManager to current area / player (so no full-memory scan each time)
