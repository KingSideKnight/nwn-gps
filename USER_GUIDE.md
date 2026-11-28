# NWN GPS: User Guide

A GPS for **Neverwinter Nights: Enhanced Edition** multiplayer servers. It maps the world as you
play, lets you search for any place you (or your friends) have been, and guides you there with
an in-game panel: arrow, distance, next step, and a live map of the area. Works in fullscreen.

> **Please read first.** NWN GPS reads the game's memory to see where you are and loads a small
> add-on into the running game to draw its panel. It never changes game files, saves or
> characters. **Some servers restrict third-party tools that read or modify the game client:
> check your server's rules before using it.** You use it at your own risk.

## What you need
- **Neverwinter Nights: Enhanced Edition** on Windows (Steam, GOG or Beamdog), game build
  **8193.37-17**. You can see your build in the game's main menu, bottom corner.
- When the game updates, NWN GPS may stop working until it gets an update too. It tells you so
  ("This game version isn't supported yet") and doesn't touch the game; your maps are kept.

## Install
NWN GPS doesn't need installing: it runs from its own folder.

1. **Download.** Open the
   [Releases page](https://github.com/KingSideKnight/nwn-gps/releases), find the newest
   version, open **Assets** and click **`NWN-GPS-<version>.zip`**. Don't pick "Source code":
   that's for developers and has no program in it.
2. **Extract.** In your Downloads folder, right-click the zip, choose **Extract All...**, pick a
   folder (for example `C:\Games\NWN-GPS`) and click **Extract**. Running it straight from inside
   the zip doesn't work. Don't put it inside the game folder.
3. **Run `NWN-GPS.exe`** from the extracted folder.
   - **"Windows protected your PC"** (a blue box): NWN GPS isn't signed by a paid certificate,
     so Windows doesn't recognise it. Click **More info**, then **Run anyway**. You only see this
     the first time.
   - **"Smart App Control blocked an app"**, with no Run anyway button: see
     [Smart App Control](#smart-app-control) below.
   - The first time, a black window shows a short notice. Read it, type `YES` and press Enter.
4. **Start Neverwinter Nights normally** (not "Run as administrator") and join a server.
   You can start NWN GPS before or after the game.

Leave the NWN GPS window open while you play (you can minimise it). Close it, or press Ctrl+C in
it, to stop. Tip: right-click `NWN-GPS.exe` and choose **Send to > Desktop (create shortcut)**
for a desktop icon.

### Is it working?
- The NWN GPS window lists the game it found, where its logs go and your keys. It stays quiet
  after that unless something goes wrong.
- Once you're in an area in game, the **GPS panel** appears near the **bottom-right** corner,
  above the compass: "NWN GPS", the area name and a small map. Ctrl+Shift + drag moves it.
- No panel after a minute? See [Troubleshooting](#troubleshooting).

### Antivirus
NWN GPS reads the game's memory and loads a small add-on into the game to draw its panel. Some
antivirus programs treat that as suspicious and quarantine `NWN-GPS.exe` or the `.dll` next to
it, even though it's harmless. If files disappear from the folder, or the window says "could not
load the in-game panel", add the NWN GPS folder as an exclusion. In Windows Security:
**Virus & threat protection > Manage settings > Exclusions > Add or remove exclusions > Add an
exclusion > Folder**. Then extract the zip again.

### Smart App Control
Smart App Control is a Windows 11 protection that only lets programs run if Microsoft already
knows them or they're signed with a code-signing certificate. Windows turns it on by itself on
new PCs and fresh installs, so you may have it without ever choosing it. Unlike the blue
SmartScreen box, it has no **Run anyway** button.

**Why it blocks NWN GPS, plainly:**
- **NWN GPS isn't signed.** Signing means buying a certificate, or using Microsoft's paid signing
  service, after an identity check. This is a free, one-person fan project, and it isn't signed
  yet. We'd like to sign future releases, but there's no date.
- **What it does looks risky to security tools.** It reads another program's memory and loads an
  add-on into it, which is exactly what cheats and some malware do too. NWN GPS only does this to
  the game, only to read your position and draw its panel, and the source code is public so
  anyone can check. Windows can't know that, and it's right to be careful.

Nothing NWN GPS can do from its side gets past Smart App Control, and we won't pretend otherwise.

**Check whether it's on:** Windows Security > **App & browser control** > **Smart App Control
settings**. It says **On**, **Evaluation** (Windows is watching and may switch it on later) or
**Off**.

**Your choices:**
1. **Wait for a signed release.** The safest choice. Keep an eye on the
   [Releases page](https://github.com/KingSideKnight/nwn-gps/releases); the notes will say when a
   release is signed.
2. **Turn Smart App Control off**, on that same settings page. Only do this if you're comfortable
   with what it means:
   - It stops protecting you from *all* unknown programs, not just NWN GPS. Windows Security's
     antivirus keeps running.
   - On many Windows 11 versions it **can't be turned back on** without resetting or
     reinstalling Windows. Read what the settings page says before you switch.
   - Only download NWN GPS from the Releases page above, and check that your zip is the real one
     (below).

**Check your download is the real one.** Each release lists the zip's SHA-256 fingerprint. In
the folder with the zip, right-click empty space, choose **Open in Terminal**, and run
`Get-FileHash NWN-GPS-<version>.zip` (with your version). The long code it prints must match the
one on the Releases page exactly. If it doesn't, delete the file and don't run it.

## Upgrading
1. Close NWN GPS. The game can keep running.
2. Download and extract the new zip as above, and replace the old NWN GPS folder (or delete the
   old folder first).
3. Run the new `NWN-GPS.exe`. If the game is already running, it swaps in its new in-game add-on
   by itself.

Your maps, settings and shared files live in `Documents\NWN GPS`, not in the program folder, so
upgrading keeps them.

## In the game
| Keys | What it does |
|---|---|
| **Ctrl+Shift+F** | Choose a destination: type to search places, then **click** a result (or ↑/↓ or the mouse wheel to pick and Enter to go). Esc cancels. With nothing typed it lists your [saved places](#saved-places) and recent destinations |
| **Ctrl+Shift+X** | Clear the destination (it also clears itself a few seconds after you arrive) |
| **Ctrl+Shift+M** | Full-screen world map (press again, or **Esc**, to close). **Click** a building, a map pin or any spot to go there. Drag it or use the arrow keys to look around, mouse wheel or **+ / -** to zoom, **Home** to jump back to you |
| **Ctrl+Shift+L** | Pin names on the full-screen map on / off (the dots stay; it remembers your choice) |
| **Ctrl+Shift+G** | Hide / show the panel |
| **Ctrl+Shift+E** | Export your map to share with friends |
| **Ctrl+Shift+I** | Import maps friends sent you |
| **Ctrl+Shift+W** | Map window on / off (experimental): the world map in its own window, e.g. on a second monitor (see [Map window](#map-window)) |
| **Ctrl+Shift + drag** | Move the panel (it remembers where you put it) |
| **Drag the small map** | Look around a big area. Let go and it glides back to following you; while you look elsewhere, a blue arrow on its edge points back to you. (Small areas already fit whole, so there's nothing to drag.) Clicks on the small map don't reach the game; clicks on the rest of the panel do |

The panel always shows these keys at the bottom (the full-screen map shows its own), so you don't
need to memorise them. To change them, press S in the NWN GPS window (see [Settings](#settings)).

**Click to go:** on the full-screen map, a click on a building's square or a map pin's dot makes it
your destination; a click anywhere else in an area sends you to that spot. The route appears on
the map straight away, and the panel guides you as usual. A click that turns into a drag just
moves the map.

## Saved places
Star the places you keep going back to (your home, a bank, a shop, a spot in the wilds) and get
there again in two key presses.

- **Save a place:** press **Ctrl+Shift+F** and, with nothing typed, pick
  - **Save where I'm standing**, or
  - **Save current destination** (whatever you're heading to now: a search result or a spot you
    clicked on the map).

  Then type a name and press **Enter**. The grey name already in the box (the nearest map pin, or
  the area's name) is used if you just press Enter. **Esc** goes back without saving. Saving
  right next to a place you saved before renames it.
- **Go there:** press **Ctrl+Shift+F**. Your saved places are listed first (with a ★), before
  recent destinations. Typing finds them too, ahead of other results.
- **See them:** they're gold stars on the small map, the full-screen map and the map window.
  Click a star to go there.
- **Remove one:** press **Ctrl+Shift+F**, select it and press **Delete** twice. Removed places
  aren't lost: `NWN-GPS.exe cli changes` lists them and `NWN-GPS.exe cli restore <id>` brings one
  back.

Saved places belong to the server's map you saved them on. They never count as doors or exits, so
they can't change your routes. They're left out of maps you export for friends unless you turn
that on in Settings, and saved places in a friend's map are never added to yours (the import
message says how many were left out).

## Map window
**Experimental:** it works, but it's new and hasn't been tried on many setups yet. If something
looks wrong, please report it, with your monitor layout and `Documents\NWN GPS\logs\mapwindow.log`.

The world map can also have a window of its own: on a second monitor, a TV, a tablet used as a
screen, or beside the game if you play in a window. It's **off until you turn it on**, with
**Ctrl+Shift+W** in the game or in Settings ("Map window"); the same key, its **Hide** button or
its X turns it off again.
- It shows the directions at the top and the world map below, following you. **Click** a place to
  go there (the in-game panel picks up the new destination too), **drag** to look around, use the
  mouse wheel or the **Zoom** buttons to zoom, and **Back to me** to follow you again. **Pin names**
  turns the names on and off, **Always on top** keeps it above other windows.
- **Where it opens:** the first time, it fills the biggest monitor the game isn't on, or, with a
  single monitor, opens as a window. Move and resize it like any window; it remembers. If that
  monitor isn't connected next time, it picks again.
- **It never takes the keyboard from the game:** clicking it doesn't switch away from the game, so
  a fullscreen game stays put. That's also why it has buttons rather than keys, and no search box
  (use **Ctrl+Shift+F** in the game). If your game keeps the mouse on its own screen, use the
  window by touch, or play in borderless fullscreen (NWN's display settings).
- It works without the in-game panel, and keeps working if the game refuses the panel.

## How mapping works
- The map grows as you explore. Every area you enter is recorded with its map pins, doors and
  the exits you use. Routes are built from the exits people have actually walked.
- An area's picture appears after you've been in it once with the GPS running.
- Outdoor areas are joined into a world map automatically; buildings appear as markers at their doors.
  Game worlds don't always fit on flat paper, so when two areas would land on top of each other,
  one of them (with everything beyond it) is moved aside and a **dashed white line** joins the exit
  to where it comes out.
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
- **Exits that go to different places:** some portals take you somewhere different each time (a
  plane that returns you to wherever you came in from, a ship or portal that asks where to go).
  Once an exit has taken you to two different areas, directions avoid it and walk instead; it's
  only used when there's no other known way, and the panel then says "This exit has led to
  different places: pick ... if asked". No way back is assumed through such an exit either.
- **Coming out in the middle of an area:** a way back is only assumed when you came out next to a
  door, a map pin or the map edge, the way a normal exit puts you. A portal that drops you in the
  middle of an area (say, the way out of a plane you teleported into) never becomes a way in.

Teleports and deaths never move areas around on the world map; only walked exits place areas.
**Inside the area you're in, directions follow the ground.** The tiles' own walkmeshes say where
you can walk, so the route goes along streets, corridors and doorways instead of through walls and
water. The arrow points at the next turn, and the distance is how far it is on foot. The first
time you enter an area it takes a moment (about a second) to work out; after that it's instant.
It doesn't know about furniture, crates or people (they aren't part of the tiles), so expect the
odd small detour, and a locked door looks like an open doorway. Where an area's tiles can't be
read, directions fall back to a straight line.

On the maps, the route line follows the areas you'll walk through. It stops at a portal or
teleport (drawn as a ringed dot) and picks up again where you come out, rather than cutting
straight across the map.
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
- **Import while you're on the same server the map is from.** Each map file knows its server, and
  a file from another server is not merged: it stays in the Inbox (the message names its server)
  until you press Ctrl+Shift+I while playing there.
- Several files at once, from one friend or many, are fine. What you've seen yourself always wins:
  a friend's map only adds what you don't have. If two friends disagree about where a door leads,
  the first one imported counts and the other is kept as untrusted.
- The same file sent twice is only imported once (the second copy just moves to `Inbox\merged`),
  and a teleport a friend saw once doesn't become a route however many of their maps you import.
- Exported maps don't include when you played (times and visit counts are removed), whose maps
  you've imported, or your [saved places](#saved-places) (unless you turn that on in Settings). They do carry a random id for your map (nothing about you), so a friend's GPS
  counts your map once.
- Imported files are checked thoroughly and anything invalid is skipped, but routes from a friend's
  map are only as good as that map: **only import maps from people you trust.** See `SECURITY.md`.

**Undoing an import:** open Settings (press **S** in the NWN GPS window), click **Imported maps...**,
pick the file and click **Undo selected import**. That file's places, routes and area maps come
back out of your map. Anything you've since seen yourself in the game stays. Your map is backed up
first, and the file stays in `Inbox\merged` if you want to import it again later.

## Settings
**Press S in the NWN GPS window** to open the Settings window (or run `NWN-GPS.exe settings`,
which works while NWN GPS isn't running too). There you can:
- **Change the keys:** click a key, then press the new combination. Esc cancels; **Reset keys
  to defaults** puts them all back. New keys work in the game a few seconds after you save.
- **Mapping:** death areas and DM mode (below).
- **Folders:** the game folder and NWN user folder, if they weren't found by themselves. These
  apply the next time you start NWN GPS.
- **Map window:** turn the [map window](#map-window) on or off (experimental).
- **Sharing:** whether maps you export for friends include your [saved places](#saved-places)
  (off unless you turn it on).
- **Updates:** turn the daily update check on or off, or **Check now** (see
  [Updates](#updates)).

Everything is saved in `Documents\NWN GPS\settings.json`, which you can also edit by hand (close
NWN GPS first):
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
- `"check_updates"`: `false` turns off the daily update check.
- `"map_window"`: `true` shows the [map window](#map-window) (what Ctrl+Shift+W switches).
- `"share_places"`: `true` puts your saved places in maps you export for friends.

## Updates
Once a day, when it starts, NWN GPS asks GitHub (where it's published) whether a newer version is
out. If there is one, the NWN GPS window shows the version and its download link, and the panel
mentions it once in the game.
- **What's sent:** one request to `api.github.com` for the list of NWN GPS releases. GitHub sees
  your IP address and that the request comes from NWN GPS (and which version). Nothing about you,
  your character, your game or your maps is sent.
- **Nothing is downloaded or installed.** To update, download the new zip yourself; see
  [Upgrading](#upgrading).
- **To turn it off:** untick it in Settings, or set `"check_updates": false` in `settings.json`.

## Troubleshooting
- **No panel in the game.** Make sure the game isn't running as administrator. If the window says
  "could not load the in-game panel", security software may be blocking it: see
  [Antivirus](#antivirus), or use the desktop alternatives below.
- **Windows says "Windows protected your PC".** Click **More info**, then **Run anyway**
  (see [Install](#install)).
- **"Smart App Control blocked an app"** and there's no Run anyway. See
  [Smart App Control](#smart-app-control): it's because NWN GPS isn't signed yet.
- **Nothing happens when I double-click `NWN-GPS.exe`**, or it says files are missing. Make sure
  you extracted the whole zip (right-click, **Extract All...**) and didn't run it from inside the
  zip. If files vanished from the folder, your antivirus removed them: see [Antivirus](#antivirus).
- **"This game version isn't supported yet."** A game update changed the parts NWN GPS reads.
  Nothing is loaded into the game in that case; wait for an NWN GPS update.
- **Routes say "No known route yet".** Nobody has recorded a way there yet: explore, or import a
  friend's map.
- **A route sends me somewhere strange** (a link that doesn't exist, e.g. from a teleport that
  happened next to a door). List the links with `NWN-GPS.exe cli links "<area name>"`, then
  `NWN-GPS.exe cli forget-link <id>` to delete a wrong one (your map is backed up first), or
  `distrust-link <id>` / `trust-link <id>` to stop or start using it for directions.
- **Alternatives without the in-game panel:** the [map window](#map-window) (Ctrl+Shift+W or
  Settings), and `NWN-GPS.exe hud` (text through RivaTuner Statistics Server).
- Logs: `Documents\NWN GPS\logs`. If a part keeps failing at startup, the NWN GPS window stops
  restarting it and shows the error.

## Your data
- Maps: `Documents\NWN GPS\data\<world>.sqlite`, with automatic backups in `data\backups\` before
  imports, restores, forgotten links and noticed layout changes.
- Nothing is uploaded anywhere. Sharing only happens when you send an exported file yourself. The
  only thing NWN GPS asks the internet is the daily update check (see [Updates](#updates)).
- To remove NWN GPS: delete its folder and `Documents\NWN GPS`.

## License
NWN GPS is free software under the MIT License (`LICENSE.txt`). It is an unofficial fan-made tool,
not affiliated with Wizards of the Coast, Beamdog or any server. Bundled components and their
licenses are listed in `THIRD_PARTY_NOTICES.txt`.
