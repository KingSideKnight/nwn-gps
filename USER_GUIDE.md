# NWN GPS: User Guide

A GPS for **Neverwinter Nights: Enhanced Edition** multiplayer servers. It maps the world as you
play, lets you search for any place you (or your friends) have been, and guides you there with
an in-game panel: arrow, distance, next step, and a live map of the area. Works in fullscreen.

> **Please read first.** NWN GPS reads the game's memory to see where you are and loads a small
> add-on into the running game to draw its panel. It never changes game files, saves or
> characters. **Some servers restrict third-party tools that read or modify the game client:
> check your server's rules before using it.** You use it at your own risk.

## Install
1. Unzip `NWN-GPS` anywhere you like (for example `C:\Games\NWN-GPS`). Not inside the game folder.
2. Run **`NWN-GPS.exe`**. The first time, it shows a short notice; type `YES` to continue.
3. Start Neverwinter Nights **normally** (not "Run as administrator") and join a server.
   You can start the GPS before or after the game.

Leave the small NWN GPS window open while you play. Close it (or press Ctrl+C in it) to stop.

## In the game
| Keys | What it does |
|---|---|
| **Ctrl+Shift+F** | Choose a destination: type to search places, ↑/↓ to pick, Enter to go, Esc to cancel |
| **Ctrl+Shift+X** | Clear the destination (it also clears itself 10 s after you arrive) |
| **Ctrl+Shift+M** | Full-screen world map (press again to close) |
| **Ctrl+Shift+G** | Hide / show the panel |
| **Ctrl+Shift+E** | Export your map to share with friends |
| **Ctrl+Shift+I** | Import maps friends sent you |
| **Ctrl+Shift + drag** | Move the panel (it remembers where you put it) |

The panel always shows these keys at the bottom, so you don't need to memorise them.

## How mapping works
- The map grows as you explore. Every area you enter is recorded with its map pins, doors and
  the exits you use. Routes are built from the exits people have actually walked.
- An area's picture appears after you've been in it once with the GPS running.
- Outdoor areas are joined into a world map automatically; buildings appear as markers at their doors.
- Servers that are split into several linked servers (like Arelith) share one map. Travel between
  them is learned the first time you use a portal (and confirmed the second time).

## Teleports, deaths and DMs
A loading screen looks the same whether you walked through a door, cast Teleport, died, or a DM
moved you, so NWN GPS judges each area change by where you were standing when it happened:

- **Doors, transition pins and map edges** are normal exits and are used for directions straight away.
- **Anywhere else** (a spell, a recall stone, a scripted portal, a graveyard respawn) is recorded as a
  *teleport spot* but not used for directions. If you take it from the same spot three times it
  becomes trusted ("Teleport spot: use the portal / object here"); a door found there later
  makes it a normal exit.
- **Dying:** arriving in a death area (Arelith's Fugue Plane by default, see `"death_areas"` below)
  is never used for directions, so you'll never be told to die to get somewhere. The way *out* of
  the death area is recorded and used, but NWN GPS never assumes you can walk back in.
- Servers that just revive you in a graveyard are covered by the teleport rule: the place you died is
  random, so that "link" is never trusted.
- Moving within the same area (a short teleport, a DM jump nearby) records nothing.

Teleports and deaths never move areas around on the world map; only walked exits place areas.
If something wrong still gets in, see "A route sends me somewhere strange" below.

**DM client (experimental, untested).** NWN GPS hasn't been tried in the DM client yet. DMs jump
around and possess creatures constantly, which would fill the map with bogus links, so set
`"dm_mode": true` before using it there: areas, map pins, doors and area maps are still recorded,
but no links between areas. NWN GPS can't tell a DM session apart by itself yet.

## When the server changes a map
Servers rebuild areas, move doors and re-point exits. NWN GPS keeps checking what it sees, and
it never deletes anything by itself: what it stops using is only hidden, and you can undo it.

- **A changed area layout** is noticed the next time you're there (it has to read the same new
  layout twice, so a half-loaded area can't overwrite a good map). The new picture replaces the old
  one, the world map redraws, and the old layout is kept.
- **A pin or door that's gone** is hidden once it has been missing on **3 visits in a row**. The
  game only loads doors near you, so a visit only counts against a pin or door if you were within
  about 15 m of it. Visits that saw too little of what's known (still loading) don't count. If it
  turns up again it's back straight away.
- **An exit that leads somewhere new:** once you walk it, older links out of that same door stop
  being used. A link whose door or pin is gone (and that isn't at the map edge) stops being used
  too. Walking an old link again makes it trusted again.
- **Friends' maps can't undo this.** Merging an older map doesn't bring back what you've seen
  removed, their own retired pins and stale links are skipped, and if their link leaves a door
  that leads somewhere else in your map, yours wins.

To see what was noticed: `NWN-GPS.exe cli changes` (or `changes "<area name>"`). To undo one:
`NWN-GPS.exe cli restore <id>`. Your map is backed up first, and a layout change also makes a
backup when it happens. If the server really did remove something, it's hidden again after 3 more
visits. `cli links` marks links that are no longer used as "stale"; `trust-link <id>` puts one
back by hand.

## Sharing maps with friends
- **Ctrl+Shift+E** saves your map to `Documents\NWN GPS\Exports`. Send that `.sqlite` file to a friend.
- Put files you receive into `Documents\NWN GPS\Inbox`, then press **Ctrl+Shift+I**.
  Your own map is backed up first; merged files move to `Inbox\merged`.
- Exported maps don't include when you played (times and visit counts are removed).
- Imported files are checked thoroughly and anything invalid is skipped, but routes from a friend's
  map are only as good as that map: **only import maps from people you trust.** See `SECURITY.md`.

## Settings
`Documents\NWN GPS\settings.json` (created on first run). Close NWN GPS before editing.
- `"hotkeys"`: change any key, e.g. `"map": "Alt+M"`. Use Ctrl, Shift and/or Alt plus A–Z, 0–9 or F1–F12.
  Invalid or duplicate keys fall back to the defaults (the NWN GPS window tells you).
- `"game_dir"`: only needed if the game isn't found automatically
  (Steam, GOG and Beamdog installs are detected).
- `"user_dir"`: only if you start NWN with a custom `-userdirectory`.
- `"death_areas"`: words that identify the areas you're sent to when you die (matched anywhere in
  the area's name or resref, any case). Default `["fugue"]`. On another server you might use e.g.
  `["fugue", "afterlife"]`.
- `"dm_mode"`: `true` records no links between areas (for the DM client, experimental, untested).
  The recorder picks this up at the next area change, no restart needed.

## Troubleshooting
- **No panel in the game.** Make sure the game isn't running as administrator. If the window says
  "could not load the in-game panel", security software may be blocking it: allow the NWN GPS
  folder, or use the desktop alternatives below.
- **"This game version isn't supported yet."** A game update changed the parts NWN GPS reads.
  Nothing is loaded into the game in that case; wait for an NWN GPS update.
- **Routes say "No known route yet".** Nobody has recorded a way there yet: explore, or import a
  friend's map.
- **A route sends me somewhere strange** (a link that doesn't exist, e.g. from a teleport that
  happened next to a door). List the links with `NWN-GPS.exe cli links "<area name>"`, then
  `NWN-GPS.exe cli forget-link <id>` to delete a wrong one (your map is backed up first), or
  `distrust-link <id>` / `trust-link <id>` to stop or start using it for directions.
- **Alternatives without the in-game panel:** `NWN-GPS.exe overlay "<place>"` (a window on top of the
  game: windowed or borderless mode, or `--other-screen` for a second monitor) and
  `NWN-GPS.exe hud` (text through RivaTuner Statistics Server).
- Logs: `Documents\NWN GPS\logs`. If a part keeps failing at startup, the NWN GPS window stops
  restarting it and shows the error.

## Your data
- Maps: `Documents\NWN GPS\data\<world>.sqlite`, with automatic backups in `data\backups\` before
  imports, restores, forgotten links and noticed layout changes.
- Nothing is uploaded anywhere. Sharing only happens when you send an exported file yourself.
- To remove NWN GPS: delete its folder and `Documents\NWN GPS`.

## License
NWN GPS is free software under the MIT License (`LICENSE.txt`). It is an unofficial fan-made tool,
not affiliated with Wizards of the Coast, Beamdog or any server. Bundled components and their
licenses are listed in `THIRD_PARTY_NOTICES.txt`.
