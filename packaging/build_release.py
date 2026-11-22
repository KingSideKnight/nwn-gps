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
    if out.exists():                 # keep runtime\: the game may have its DLL loaded from there
        for child in out.iterdir():
            if child.name != "runtime":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    stage = WORK / "dist"            # PyInstaller wipes its output folder, so build to a staging area
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
         "--name", "NWN-GPS", "--distpath", str(stage), "--workpath", str(WORK), "--specpath", str(WORK),
         "--collect-submodules", "nwngps",
         "--add-data", f"{dll};.",
         "--exclude-module", "nwngps.launcher_test",
         str(ROOT / "packaging" / "entry.py")], cwd=ROOT)
    out.mkdir(parents=True, exist_ok=True)
    for child in (stage / "NWN-GPS").iterdir():
        dest = out / child.name
        shutil.copytree(child, dest) if child.is_dir() else shutil.copy2(child, dest)
    # the bundled DLL is looked up by this exact name
    internal = out / "_internal"
    if (internal / dll.name).exists() and dll.name != "nwngps_gl.dll":
        (internal / dll.name).rename(internal / "nwngps_gl.dll")
    for name in ("USER_GUIDE.md", "LICENSE", "THIRD_PARTY_NOTICES.txt"):
        shutil.copy2(ROOT / name, out / (name + ".txt" if name == "LICENSE" else name))
    (out / "README.txt").write_text(
        f"NWN GPS {__version__}\r\n\r\nRun NWN-GPS.exe, then start Neverwinter Nights normally.\r\n"
        "Read USER_GUIDE.md for keys, map sharing, settings and troubleshooting.\r\n\r\n"
        "NWN GPS reads the game's memory and loads a small add-on into the running game to draw its\r\n"
        "panel. It never changes game files. Check your server's rules about third-party tools.\r\n\r\n"
        "Free software under the MIT License (LICENSE.txt). Unofficial fan-made tool, not affiliated\r\n"
        "with Wizards of the Coast or Beamdog (see THIRD_PARTY_NOTICES.txt).\r\n",
        encoding="utf-8")
    zpath = DIST / f"NWN-GPS-{__version__}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in out.rglob("*"):
            if f.is_file() and "runtime" not in f.relative_to(out).parts:
                z.write(f, Path("NWN-GPS") / f.relative_to(out))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\nbuilt {out} ({size / 1e6:.1f} MB) and {zpath} ({zpath.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
