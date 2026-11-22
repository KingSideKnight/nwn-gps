"""PyInstaller entry point for NWN-GPS.exe."""
from nwngps.__main__ import guarded_main

if __name__ == "__main__":
    guarded_main()
