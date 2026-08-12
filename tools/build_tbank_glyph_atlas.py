"""Build K-TBANK-GLYPH-ATLAS-001 v3 — full atlas bundle from confirmed originals."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from detector.reputation import file_hash
from detector.tbank_glyph_atlas import (
    extract_glyph_observations,
    merge_atlas_samples,
    save_atlas_bundle,
)

# Confirmed T-Bank originals only — do not rglob Downloads (Sber/Ozon noise).
CORPUS_DIRS = [
    Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\Новая папка"),
]


def _collect_pdfs() -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for d in CORPUS_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.pdf")):
            key = p.resolve().as_posix().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def main() -> int:
    pdfs = _collect_pdfs()
    if not pdfs:
        print("no PDFs")
        return 1

    samples = []
    errors = 0
    for p in pdfs:
        try:
            data = p.read_bytes()
            obs = extract_glyph_observations(data, source=f"{p.name}:{file_hash(data)[:16]}")
            n = sum(len(g) for g in obs.get("glyphs", {}).values())
            if n:
                samples.append(obs)
                print(f"OK {p.name} glyphs={n}")
            else:
                print(f"SKIP {p.name}")
        except Exception as exc:
            errors += 1
            print(f"ERR {p.name}: {exc}")

    if not samples:
        print("no samples")
        return 1

    atlas = merge_atlas_samples(samples)
    paths = save_atlas_bundle(atlas)
    print(f"written v={atlas['version']} total_glyphs={atlas['total_glyph_count']} samples={len(samples)}")
    for fk in ("F1", "F2", "F3"):
        print(f"  {fk}: {atlas['fonts'][fk]['glyph_count']} -> {paths.get(fk)}")
    print(f"  subset_builder: {paths.get('subset_builder')}")
    print(f"  index: {paths.get('index')}")
    if atlas.get("render_stats"):
        print("render_stats", atlas["render_stats"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
