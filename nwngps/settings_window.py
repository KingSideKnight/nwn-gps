"""Settings window: change keys and options without editing settings.json.

  NWN-GPS.exe settings      (or press S in the NWN GPS window)

Saves Documents\\NWN GPS\\settings.json. A running GPS picks up new keys within a few seconds and
the recorder picks up the map options at the next area change; the game folders apply the next
time NWN GPS starts.
"""
import ctypes
import os
import threading
from pathlib import Path

from . import config, hotkeys

MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}
VK_ESCAPE, VK_BACK = 0x1B, 0x08


def key_text(vk, mods):
    """(virtual key, mods 1 Shift / 2 Ctrl / 4 Alt) -> 'Ctrl+Shift+F', or None for keys we can't use."""
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        key = chr(vk)
    elif 0x70 <= vk <= 0x7B:
        key = f"F{vk - 0x6F}"
    else:
        return None
    names = [n for bit, n in ((2, "Ctrl"), (1, "Shift"), (4, "Alt")) if mods & bit]
    return "+".join(names + [key]) if names else None


def held_mods():
    """Modifier keys held right now (Windows), as hotkeys mods bits."""
    get = ctypes.windll.user32.GetKeyState
    return (1 if get(0x10) < 0 else 0) | (2 if get(0x11) < 0 else 0) | (4 if get(0x12) < 0 else 0)


def validate(values, base):
    """Form values -> (settings to save, list of problems). `base` is the current settings."""
    problems, keys, seen = [], {}, {}
    for action in hotkeys.ORDER:
        text = (values["hotkeys"].get(action) or "").strip()
        try:
            vk_mods = hotkeys.parse(text)
        except ValueError as e:
            problems.append(f"{hotkeys.LABELS[action]}: {e}")
            continue
        if vk_mods in seen:
            problems.append(f"{text} is used for both {hotkeys.LABELS[seen[vk_mods]]} and {hotkeys.LABELS[action]}")
        seen[vk_mods] = action
        keys[action] = text
    game = values["game_dir"].strip()
    if game and not config._valid(game):
        problems.append("Game folder: that folder doesn't contain bin\\win32\\nwmain.exe "
                        "(leave it empty to find the game by itself)")
    user = values["user_dir"].strip()
    if user and not Path(user).is_dir():
        problems.append("NWN user folder: that folder doesn't exist (leave it empty for the usual one)")
    deaths = [w.strip() for w in values["death_areas"].split(",") if w.strip()]
    out = dict(base)
    out.update(hotkeys=keys, game_dir=game, user_dir=user, death_areas=deaths,
               check_updates=bool(values["check_updates"]), dm_mode=bool(values["dm_mode"]))
    return out, problems


def main():
    import tkinter as tk
    from tkinter import filedialog, ttk
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)        # sharp text on scaled displays
    except (AttributeError, OSError):
        pass
    s = config.load_settings()
    root = tk.Tk()
    root.title("NWN GPS Settings")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky="nsew")
    row = 0

    def heading(text):
        nonlocal row
        ttk.Label(frm, text=text, font=("Segoe UI", 11, "bold")).grid(row=row, column=0, columnspan=3,
                                                                    sticky="w", pady=(12 if row else 0, 4))
        row += 1

    heading("Keys in the game")
    ttk.Label(frm, text="Click a key, then press the new combination (Ctrl, Shift and/or Alt plus a letter, "
                        "digit or F1-F12). Esc cancels.", wraplength=520, foreground="#555").grid(
        row=row, column=0, columnspan=3, sticky="w")
    row += 1
    key_vars, buttons = {}, {}
    capturing = {"action": None}

    def stop_capture():
        a = capturing["action"]
        if a:
            buttons[a].configure(text=key_vars[a].get())
        capturing["action"] = None

    def start_capture(action):
        stop_capture()
        capturing["action"] = action
        buttons[action].configure(text="press keys...")
        buttons[action].focus_set()

    def on_key(event):
        a = capturing["action"]
        if not a:
            return None
        vk = event.keycode                                    # Windows virtual-key code
        if vk in MODIFIER_VKS:
            return "break"
        if vk == VK_ESCAPE:
            stop_capture()
            return "break"
        text = key_text(vk, held_mods())
        if text is None:
            status.configure(text="Use Ctrl, Shift and/or Alt plus a letter, a digit or F1-F12.", foreground="#b00")
            return "break"
        key_vars[a].set(text)
        status.configure(text="")
        stop_capture()
        return "break"

    for action in hotkeys.ORDER:
        key_vars[action] = tk.StringVar(value=s["hotkeys"].get(action) or config.DEFAULT_HOTKEYS[action])
        ttk.Label(frm, text=hotkeys.LABELS[action]).grid(row=row, column=0, sticky="w", padx=(0, 12))
        b = ttk.Button(frm, text=key_vars[action].get(), width=18, command=lambda a=action: start_capture(a))
        b.grid(row=row, column=1, sticky="w", pady=1)
        b.bind("<KeyPress>", on_key)
        buttons[action] = b
        row += 1

    def reset_keys():
        stop_capture()
        for a, v in key_vars.items():
            v.set(config.DEFAULT_HOTKEYS[a])
            buttons[a].configure(text=v.get())
    ttk.Button(frm, text="Reset keys to defaults", command=reset_keys).grid(row=row, column=1, sticky="w", pady=(4, 0))
    row += 1

    heading("Mapping")
    death = tk.StringVar(value=", ".join(s.get("death_areas") or []))
    ttk.Label(frm, text="Death areas").grid(row=row, column=0, sticky="w")
    ttk.Entry(frm, textvariable=death, width=40).grid(row=row, column=1, columnspan=2, sticky="we")
    row += 1
    ttk.Label(frm, text="Words in the names of the areas you're sent to when you die (comma separated).",
              foreground="#555").grid(row=row, column=1, columnspan=2, sticky="w")
    row += 1
    dm = tk.BooleanVar(value=bool(s.get("dm_mode")))
    ttk.Checkbutton(frm, text="DM mode: record no links between areas (experimental)", variable=dm).grid(
        row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))
    row += 1

    heading("Folders")
    dirs = {}
    for key, label, hint in (("game_dir", "Game folder", "empty = find it by itself"),
                             ("user_dir", "NWN user folder", "empty = Documents\\Neverwinter Nights")):
        dirs[key] = tk.StringVar(value=s.get(key) or "")
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=dirs[key], width=40).grid(row=row, column=1, sticky="we")
        ttk.Button(frm, text="Browse...", command=lambda k=key: dirs[k].set(
            filedialog.askdirectory(parent=root, initialdir=dirs[k].get() or None) or dirs[k].get())).grid(
            row=row, column=2, padx=(6, 0))
        row += 1
        ttk.Label(frm, text=hint, foreground="#555").grid(row=row, column=1, sticky="w")
        row += 1

    heading("Updates")
    upd = tk.BooleanVar(value=s.get("check_updates", True) is not False)
    ttk.Checkbutton(frm, text="Check once a day whether a newer NWN GPS is out (asks github.com; "
                              "nothing is downloaded)", variable=upd).grid(row=row, column=0, columnspan=3, sticky="w")
    row += 1
    upd_status = ttk.Label(frm, text="", foreground="#555")

    def check_now():
        from . import updates
        upd_status.configure(text="Asking GitHub...")

        def work():
            status_, version, url = updates.check(config.load_settings(), force=True)
            msg = {"new": f"NWN GPS {version} is available: {url}", "current": "You have the newest version.",
                   "failed": "Couldn't reach GitHub. Try again later."}.get(status_, status_)
            root.after(0, lambda: upd_status.configure(text=msg))
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(frm, text="Check now", command=check_now).grid(row=row, column=0, sticky="w", pady=(4, 0))
    upd_status.grid(row=row, column=1, columnspan=2, sticky="w", pady=(4, 0))
    row += 1

    status = ttk.Label(frm, text="", wraplength=520)
    status.grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))
    row += 1
    bar = ttk.Frame(frm)
    bar.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 0))

    def save():
        stop_capture()
        values = {"hotkeys": {a: v.get() for a, v in key_vars.items()}, "game_dir": dirs["game_dir"].get(),
                  "user_dir": dirs["user_dir"].get(), "death_areas": death.get(), "check_updates": upd.get(),
                  "dm_mode": dm.get()}
        new, problems = validate(values, config.load_settings())
        if problems:
            status.configure(text="Not saved:\n" + "\n".join(problems), foreground="#b00")
            return
        config.save_settings(new)
        status.configure(text="Saved. New keys work in the game within a few seconds; folder changes apply "
                              "the next time you start NWN GPS.", foreground="#070")

    ttk.Button(bar, text="Open NWN GPS folder", command=lambda: os.startfile(config.SHARE_DIR)).pack(side="left")
    ttk.Button(bar, text="Close", command=root.destroy).pack(side="right")
    ttk.Button(bar, text="Save", command=save).pack(side="right", padx=(0, 6))
    root.mainloop()


if __name__ == "__main__":
    main()
