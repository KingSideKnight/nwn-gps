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

## Sharing maps with friends
- **Ctrl+Shift+E** saves your map to `Documents\NWN GPS\Exports`. Send that `.sqlite` file to a friend.
- Put files you receive into `Documents\NWN GPS\Inbox`, then press **Ctrl+Shift+I**.
  Your own map is backed up first; merged files move to `Inbox\merged`.

## Settings
`Documents\NWN GPS\settings.json` (created on first run). Close NWN GPS before editing.
- `"hotkeys"`: change any key, e.g. `"map": "Alt+M"`. Use Ctrl, Shift and/or Alt plus A–Z, 0–9 or F1–F12.
  Invalid or duplicate keys fall back to the defaults (the NWN GPS window tells you).
- `"game_dir"`: only needed if the game isn't found automatically
  (Steam, GOG and Beamdog installs are detected).
- `"user_dir"`: only if you start NWN with a custom `-userdirectory`.

## Troubleshooting
- **No panel in the game.** Make sure the game isn't running as administrator. If the window says
  "could not load the in-game panel", security software may be blocking it: allow the NWN GPS
  folder, or use the desktop alternatives below.
- **"This game version isn't supported yet."** A game update changed the parts NWN GPS reads.
  Nothing is loaded into the game in that case; wait for an NWN GPS update.
- **Routes say "No known route yet".** Nobody has recorded a way there yet: explore, or import a
  friend's map.
- **Alternatives without the in-game panel:** `NWN-GPS.exe overlay "<place>"` (a window on top of the
  game: windowed or borderless mode, or `--other-screen` for a second monitor) and
  `NWN-GPS.exe hud` (text through RivaTuner Statistics Server).
- Logs: `%LOCALAPPDATA%\NWN GPS\logs`.

## Your data
- Maps: `%LOCALAPPDATA%\NWN GPS\<world>.sqlite`, with automatic backups in `backups\` before imports.
- Nothing is uploaded anywhere. Sharing only happens when you send an exported file yourself.
- To remove NWN GPS: delete its folder, `%LOCALAPPDATA%\NWN GPS` and `Documents\NWN GPS`.
