#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка detector/glyph_libraries/<bank>.json из Desktop/чеки.

Библиотека: символ -> множество контуров глифа (по всем оригиналам банка).
Собираем только для банков с одним встроенным TTF-шрифтом (VTB/Sber/Alfa/
Gazprom/OTP/Ozon и т.п.). Мультишрифтовые (Т-Банк) пропускаем — у них свой движок.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.glyph_library import build_library, extract_char_glyphs

CHEKI = Path(os.environ.get("CHEKI_DIR", Path.home() / "OneDrive" / "Desktop" / "чеки"))
OUT_DIR = ROOT / "detector" / "glyph_libraries"

FOLDER_KEYS = {
    "альфа": "alfa",
    "втб": "vtb",
    "газпромбанк": "gazprombank",
    "озонбанк": "ozon",
    "отп банк": "otp",
    "псб": "psb",
    "райф": "raif",
    "сбер": "sber",
    "уралсиб": "uralsib",
    "яндекс банк": "yandex",
    "совком": "sovkom",
    "рокетбанк": "rocket",
    "бчпб": "bchpb",
}

# Т-Банк исключаем (мультишрифт F1/F2/F3 — свой движок)
SKIP = {"tbank"}

MIN_SAMPLES = int(os.environ.get("MIN_GLYPH_SAMPLES", "5"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = os.environ.get("ONLY_BANK", "").strip().lower()
    index = {}
    for folder_name, key in FOLDER_KEYS.items():
        if key in SKIP:
            continue
        if only and key != only:
            continue
        folder = CHEKI / folder_name
        if not folder.is_dir():
            print(f"skip missing {folder_name}")
            continue
        profiles = []
        used_files = 0
        for pdf in sorted(folder.glob("*.pdf")):
            prof = extract_char_glyphs(pdf.read_bytes())
            if prof:
                profiles.append(prof)
                used_files += 1
        if used_files < MIN_SAMPLES:
            print(f"  {key:12} only {used_files} single-font samples (<{MIN_SAMPLES}) — skip")
            continue
        lib = build_library(profiles)
        lib["key"] = key
        out = OUT_DIR / f"{key}.json"
        out.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
        index[key] = {"chars": len(lib["chars"]), "samples": lib["source_count"]}
        print(f"Wrote {out}  chars={len(lib['chars'])} samples={lib['source_count']}")

    if index and not only:
        (OUT_DIR / "_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Done.")


if __name__ == "__main__":
    main()
