"""Field offsets for client objects, build 26c6e573 (Oct 6 2025).
Discovered in recon; see recon/FINDINGS.md. Re-verify after game patches."""

# vtable RVAs (find_vtables.py)
VTABLES = {
    "CNWCArea": 0xE45A38,
    "CNWCCreature": 0xE474E8,
    "CNWCDoor": 0xE52F68,
    "CNWCTrigger": 0xE533F8,
    "CNWCMapPin": 0xE72800,
    "CNWCPlaceable": 0xE53950,
    "CNWCModule": 0xE44D18,
}

# Pointer chains (offsets applied as: p = *(p + off) for each)
G_APP_MANAGER = 0x12DF970                    # exported global RVA
CHAIN_CLIENT_INTERNAL = [0x0, 0x8]           # CAppManager -> CClientExoApp -> internal
INTERNAL_MODULE = 0x30                       # -> CNWCModule*
MODULE_CURRENT_AREA = 0xF8                   # -> CNWCArea*
INTERNAL_PLAYER_HOLDER = 0x640               # -> unknown object (player?)
HOLDER_CREATURE = 0xE8                       # -> CNWCCreature* (our character)

# CNWCObject common header
OBJ_ID = 0x08          # uint32 client object id
OBJ_AREA = 0x30        # CNWCArea*
OBJ_POS = 0x38         # float x, y, z
OBJ_FACING = 0x44      # float x, y, z (unit vector)

# CNWCArea
AREA_OBJ_ID = 0x118    # uint32
AREA_RESREF = 0x128    # char[16] inline
AREA_TILESET = 0x150   # char[16] inline
AREA_NAME = 0x238      # char* (CExoString)
AREA_WIDTH = 0x2A0     # int32 tiles (unverified: 10x10 seen)
AREA_HEIGHT = 0x2A4

AREA_PINS = 0x2B8      # CExoArrayList<CNWCMapPin*> {ptr, int size, int cap}
AREA_OBJECT_IDS = 0x318  # CExoArrayList<OBJECT_ID>: every object in the area
AREA_SOUND_IDS = 0x2C8   # CExoArrayList<OBJECT_ID>: sound objects
AREA_PLACEABLE_IDS = 0x338

# Client object table: hash array of node* indexed by (id & 0x7FFFFFFF) % N,
# node = {u32 key, pad, CGameObject* obj, node* next}
OBJTABLE_BUCKETS = 65536
NODE_KEY, NODE_OBJ, NODE_NEXT = 0x0, 0x8, 0x10

# CNWCMapPin
PIN_TEXT = 0x178       # char* (CExoString)

# CNWCDoor
DOOR_NAME = 0x170      # char*
DOOR_TAG = 0x1C8       # char*

# CNWCModule
MODULE_NAME = 0x18     # char*
MODULE_NWSYNC_URL = 0xB0
