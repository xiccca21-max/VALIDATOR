# -*- coding: utf-8 -*-
"""Alfa Oracle BIP 12.2.1.4 decisive-font regression + technical report."""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from detector.alfa import analyze
from detector.alfa_v2.fonts import check_fonts

ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
ZIP_ORIG = Path(r"C:\Users\fanis\Downloads\альфа-ориги.zip")
FAKES = [
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие\alfa_sbp_013424.pdf"),
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие\alfa_sbp_014046.pdf"),
]

DECISIVE = {
    "ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT",
    "ALFA_FONT_DESCRIPTOR_HEAD_BBOX_CONFLICT",
    "ALFA_USED_GLYPH_OUTLINE_ATLAS_CONFLICT",
    "ALFA_USED_GLYPH_METRIC_CONFLICT",
    "ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION",
}


def _report(label: str, pdf: bytes) -> dict:
    doc = fitz.open(stream=pdf, filetype="pdf")
    producer = (doc.metadata or {}).get("producer") or ""
    doc.close()
    fonts = check_fonts(pdf, producer=producer)
    result = analyze(pdf)
    head = fonts.stats.get("ttf_head_report") or {}
    flags = result.get("flags") or []
    decisive = [f for f in flags if any(c in f for c in DECISIVE)]
    return {
        "file": label,
        "exact_oracle_profile": fonts.stats.get("exact_oracle_profile"),
        "head.flags": head.get("flags"),
        "head.indexToLocFormat": head.get("indexToLocFormat"),
        "pdf_bbox": head.get("pdf_bbox"),
        "calculated_bbox": head.get("calculated_bbox"),
        "conflicting_glyphs": fonts.stats.get("conflicting_glyphs") or [],
        "extra_printable_glyphs": fonts.stats.get("extra_printable_glyphs") or [],
        "decisive_flags": decisive or flags[:8],
        "final_verdict": result.get("verdict"),
    }


def main() -> int:
    rows: list[dict] = []
    fp = 0
    clean = 0

    with zipfile.ZipFile(ZIP_ORIG) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
        print(f"originals in zip: {len(names)}")
        for name in sorted(names):
            pdf = zf.read(name)
            row = _report(os.path.basename(name), pdf)
            rows.append(row)
            if row["final_verdict"] != "ЧИСТО":
                fp += 1
                print("FP", row["file"], row["final_verdict"], row["decisive_flags"][:2])
            else:
                clean += 1

    fake_ok = 0
    for path in FAKES:
        pdf = path.read_bytes()
        row = _report(path.name, pdf)
        rows.append(row)
        print("--- FAKE ---")
        print(json.dumps(row, ensure_ascii=False, indent=2))
        if row["final_verdict"] == "ФЕЙК":
            fake_ok += 1
        else:
            print("MISS", path.name)

    print()
    print(f"originals CLEAN: {clean}/{len(names)}  FP={fp}")
    print(f"fakes FAKE: {fake_ok}/{len(FAKES)}")
    out = ROOT / "tools" / "_alfa_oracle_font_regression_report.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0 if fp == 0 and fake_ok == len(FAKES) and clean == len(names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
