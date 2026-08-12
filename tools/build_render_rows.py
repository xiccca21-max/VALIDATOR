#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Построить detector/tbank_render_rows.json из оригиналов Т-Банка."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from detector.render_fingerprint import merge_rows_into_library, save_row_library

ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")


def main() -> None:
    lib: dict[int, set[str]] = defaultdict(set)
    n = 0
    for p in sorted(ORIG.glob("*.pdf")):
        lib = merge_rows_into_library(p.read_bytes(), lib)
        n += 1
    save_row_library(lib, version=1)
    print(f"built render library from {n} originals, {len(lib)} row indices")


if __name__ == "__main__":
    main()
