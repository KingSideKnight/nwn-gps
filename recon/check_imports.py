"""Sanity: every `from nwngps... import name` and `layout.NAME` / `L.NAME` reference in the project
points at something that exists. Usage: python recon/check_imports.py"""
import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
problems = []
layout = importlib.import_module("nwngps.layout")
for f in sorted(list(ROOT.glob("nwngps/*.py")) + list(ROOT.glob("recon/*.py")) + list(ROOT.glob("tests/*.py"))
                + list(ROOT.glob("packaging/*.py"))):
    tree = ast.parse(f.read_text(encoding="utf-8-sig"))
    pkg = "nwngps" if f.parent.name == "nwngps" else None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and pkg:
                mod = f"{pkg}.{mod}" if mod else pkg
            if not mod.startswith("nwngps"):
                continue
            try:
                m = importlib.import_module(mod)
            except Exception as e:                       # noqa: BLE001
                problems.append(f"{f.relative_to(ROOT)}:{node.lineno}: import {mod}: {e}")
                continue
            for alias in node.names:
                if alias.name != "*" and not hasattr(m, alias.name):
                    try:
                        importlib.import_module(f"{mod}.{alias.name}")
                    except ImportError:
                        problems.append(f"{f.relative_to(ROOT)}:{node.lineno}: {mod} has no {alias.name}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "L":
            if not hasattr(layout, node.attr):
                problems.append(f"{f.relative_to(ROOT)}:{node.lineno}: layout has no {node.attr}")
print("\n".join(problems) or "all nwngps imports and layout references resolve")
sys.exit(1 if problems else 0)
