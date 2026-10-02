#!/usr/bin/env python3
"""Build the lightweight GitHub Pages shell.

Changing sudofx operational state must not rebuild Pages. The shell is copied
from versioned source and fetches changing public-safe data from the disposable
sudofx-live projection branch at runtime.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web"
TARGET = ROOT / "site"

if TARGET.exists():
    shutil.rmtree(TARGET)
shutil.copytree(SOURCE, TARGET)
print(f"built static shell: {TARGET}")
