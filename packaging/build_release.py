"""Build the player release: dist/NWN-GPS/ (NWN-GPS.exe + DLL + guide) and dist/NWN-GPS-<version>.zip.

  python packaging/build_release.py

Needs: Visual Studio 2022 C++ tools (for the DLL), Pillow, PyInstaller.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, WORK = ROOT / "dist", ROOT / "build" / "pyinstaller"
sys.path.insert(0, str(ROOT))
from nwngps import __version__  # noqa: E402


def run(cmd, **kw):
    print(">", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, **kw)


def main():
    run(["cmd", "/c", str(ROOT / "native" / "build.cmd")])
    dll = ROOT / "native" / "build" / "nwngps_gl.dll"
    new = ROOT / "native" / "build" / "nwngps_gl_new.dll"
    if new.exists() and (not dll.exists() or new.stat().st_mtime > dll.stat().st_mtime):
        dll = new                                   # build.cmd couldn't replace a file in use
    out = DIST / "NWN-GPS"
    stage = WORK / "dist"            # PyInstaller wipes its output folder, so build to a staging area
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
         "--name", "NWN-GPS", "--distpath", str(stage), "--workpath", str(WORK), "--specpath", str(WORK),
         "--collect-submodules", "nwngps",
         "--add-data", f"{dll};.",
         "--exclude-module", "nwngps.launcher_test",
         str(ROOT / "packaging" / "entry.py")], cwd=ROOT)
    staged = stage / "NWN-GPS"
    # the bundled DLL is looked up by this exact name
    internal = staged / "_internal"
    if (internal / dll.name).exists() and dll.name != "nwngps_gl.dll":
        (internal / dll.name).rename(internal / "nwngps_gl.dll")
    for name in ("USER_GUIDE.md", "LICENSE", "THIRD_PARTY_NOTICES.txt", "SECURITY.md"):
        shutil.copy2(ROOT / name, staged / (name + ".txt" if name == "LICENSE" else name))
    (staged / "README.txt").write_text(
        f"NWN GPS {__version__}\r\n\r\nRun NWN-GPS.exe, then start Neverwinter Nights normally.\r\n"
        "Read USER_GUIDE.md for keys, map sharing, settings and troubleshooting.\r\n\r\n"
        "NWN GPS reads the game's memory and loads a small add-on into the running game to draw its\r\n"
        "panel. It never changes game files. Check your server's rules about third-party tools.\r\n\r\n"
        "Free software under the MIT License (LICENSE.txt). Unofficial fan-made tool, not affiliated\r\n"
        "with Wizards of the Coast or Beamdog (see THIRD_PARTY_NOTICES.txt).\r\n",
        encoding="utf-8")
    # the zip is made from the staged build, so it never depends on what's running from dist\
    zpath = DIST / f"NWN-GPS-{__version__}.zip"
    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in staged.rglob("*"):
            if f.is_file():
                z.write(f, Path("NWN-GPS") / f.relative_to(staged))
    size = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file())
    print(f"\nbuilt {zpath} ({zpath.stat().st_size / 1e6:.1f} MB zipped, {size / 1e6:.1f} MB unpacked)")
    # refresh the runnable copy in dist\NWN-GPS (keeps runtime\, where the game may hold the DLL)
    try:
        out.mkdir(parents=True, exist_ok=True)
        exe = out / "NWN-GPS.exe"
        if exe.exists():
            with open(exe, "r+b"):       # fails while NWN GPS is running: check before deleting anything
                pass
        for child in out.iterdir():
            if child.name != "runtime":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        for child in staged.iterdir():
            dest = out / child.name
            shutil.copytree(child, dest) if child.is_dir() else shutil.copy2(child, dest)
        print(f"updated {out}")
    except OSError as e:
        print(f"NOTE: {out} is in use (is NWN GPS running?) and was not updated: {e}\n"
              f"      Stop NWN GPS and run this again to refresh it; the zip above is complete.")


if __name__ == "__main__":
    main()
