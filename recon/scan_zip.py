"""Scan every file in a release zip for personal strings (raw bytes, plus UTF-16 for Windows paths).
Usage: python scan_zip.py <zip> <needle> [<needle> ...]"""
import sys
import zipfile
from collections import Counter

z = zipfile.ZipFile(sys.argv[1])
hits = Counter()
examples = {}
for name in z.namelist():
    data = z.read(name)
    for needle in sys.argv[2:]:
        for form in (needle.encode(), needle.encode("utf-16-le")):
            i = data.find(form)
            if i >= 0:
                hits[needle] += 1
                examples.setdefault(needle, []).append(
                    (name, data[max(0, i - 40):i + 60].decode("latin-1", "replace").replace("\0", "")))
for needle in sys.argv[2:]:
    print(f"{needle!r}: {hits[needle]} files")
    for name, ctx in examples.get(needle, [])[:4]:
        print(f"    {name}: ...{ctx!r}...")
