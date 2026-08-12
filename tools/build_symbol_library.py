#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build per-bank/channel symbol library (glyph/cid/cmap).

Usage:
  python tools/build_symbol_library.py sber sbp
  python tools/build_symbol_library.py alfa sbp
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.profiles import analyze
from detector.symbol_library import extract_symbol_profile, merge_symbol_library

CHEKI = Path(os.environ.get("CHEKI_DIR", Path.home() / "OneDrive" / "Desktop" / "чеки"))
OUT_DIR = ROOT / "detector" / "symbol_libraries"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FOLDER_BY_BANK = {
    "sber": "сбер",
    "alfa": "альфа",
    "tbank": "т банк",
    "vtb": "втб",
    "gazprombank": "газпромбанк",
    "ozon": "озонбанк",
    "otp": "отп банк",
    "psb": "псб",
    "raif": "райф",
    "uralsib": "уралсиб",
    "yandex": "яндекс банк",
    "sovkom": "совком",
    "rocket": "рокетбанк",
    "bchpb": "бчпб",
}


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python tools/build_symbol_library.py <bank_key> <channel>")
        return 2
    bank_key = sys.argv[1].strip().lower()
    channel = sys.argv[2].strip().lower()

    folder_name = FOLDER_BY_BANK.get(bank_key)
    if not folder_name:
        print(f"Unknown bank key: {bank_key}")
        return 2

    folder = CHEKI / folder_name
    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 1

    samples = []
    used_files: list[str] = []
    for p in sorted(folder.glob("*.pdf")):
        data = p.read_bytes()
        r = analyze(data, p.stem)
        d = r.get("details") or {}
        if d.get("bank_key") != bank_key:
            continue
        if d.get("channel") != channel:
            continue
        prof = extract_symbol_profile(data)
        if not prof.get("fonts"):
            print(f"  SKIP {p.name} (no usable font/cmap profile)")
            continue
        samples.append(prof)
        used_files.append(p.name)
        print(f"  OK {p.name}")

    if not samples:
        print(f"No samples for bank={bank_key} channel={channel}")
        return 1

    lib = merge_symbol_library(samples)
    lib["bank_key"] = bank_key
    lib["channel"] = channel
    lib["source_files"] = used_files
    lib["source_count"] = len(used_files)

    out = OUT_DIR / f"{bank_key}_{channel}.json"
    out.write_text(json.dumps(lib, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    for fk, fd in (lib.get("fonts") or {}).items():
        print(
            f"  {fk}: chars={len(fd.get('chars') or {})}, "
            f"ttf_size={fd.get('ttf_size')}, cmap={fd.get('cmap_cids')}, used={fd.get('used_cids')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
