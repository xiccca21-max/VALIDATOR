"""Regression for sber_v2 exact sbp_outgoing HARD contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.sber_v2 import analyze  # noqa: E402

NEW_CODES = [
    "SBER_FONT_W_QUANTIZER_MISMATCH",
    "SBER_FONT_REVERSE_GLYPH_CLOSURE",
    "SBER_STATIC_TEXT_ADVANCE_MISMATCH",
    "SBER_SEPARATOR_ADVANCE_MISMATCH",
    "SBER_HEADER_DATE_CENTER_MISMATCH",
    "SBER_SBP_MARKER_INVALID",
    "SBER_AMOUNT_RUBLE_SPACING_INVALID",
    "SBER_HEADER_TRAILING_PADDING",
    "SBER_FIO_TRAILING_PADDING",
    "SBER_RECIPIENT_INITIAL_PUNCTUATION",
]

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\сбер")
FAKE_211001 = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\sber_sbp_211001.pdf")
FAKE_202951 = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\sber_sbp_202951.pdf")

EXPECTED_211001 = set(NEW_CODES)
EXPECTED_202951 = {
    "SBER_FONT_W_QUANTIZER_MISMATCH",
    "SBER_FONT_REVERSE_GLYPH_CLOSURE",
    "SBER_STATIC_TEXT_ADVANCE_MISMATCH",
    "SBER_SEPARATOR_ADVANCE_MISMATCH",
    "SBER_HEADER_DATE_CENTER_MISMATCH",
}


def _codes_from_result(r: dict) -> set[str]:
    codes: set[str] = set()
    for e in r.get("flags") or []:
        if isinstance(e, str) and e.startswith("[") and "]" in e:
            codes.add(e[1 : e.index("]")])
    return codes


def _exact_stats(r: dict) -> dict:
    details = r.get("details") or {}
    stats = details.get("stats") or {}
    return stats.get("sbp_exact_profile") or {}


def run_one(path: Path) -> tuple[str, set[str], dict]:
    r = analyze(path.read_bytes())
    return str(r.get("verdict") or ""), _codes_from_result(r), _exact_stats(r)


def main() -> int:
    print("=== FAKE 211001 ===")
    v, codes, stats = run_one(FAKE_211001)
    hit = sorted(codes & EXPECTED_211001)
    miss = sorted(EXPECTED_211001 - codes)
    print("verdict:", v)
    print("exact:", stats.get("exact_sbp_outgoing_jasper"))
    print("orphan_glyphs:", stats.get("orphan_glyphs"))
    print("hit:", hit)
    print("miss:", miss)
    print("extra_new:", sorted((codes & set(NEW_CODES)) - EXPECTED_211001))

    print("\n=== FAKE 202951 ===")
    v2, codes2, stats2 = run_one(FAKE_202951)
    hit2 = sorted(codes2 & EXPECTED_202951)
    miss2 = sorted(EXPECTED_202951 - codes2)
    print("verdict:", v2)
    print("exact:", stats2.get("exact_sbp_outgoing_jasper"))
    print("orphan_glyphs:", stats2.get("orphan_glyphs"))
    print("hit 1-5:", hit2)
    print("miss 1-5:", miss2)
    print("also new:", sorted(codes2 & set(NEW_CODES)))

    print("\n=== ORIGINALS CORPUS ===")
    pdfs = sorted(CORPUS.glob("*.pdf"))
    print("count:", len(pdfs))
    any_new = 0
    exact_clean = 0
    exact_total = 0
    dirty: list[str] = []
    for p in pdfs:
        v, codes, stats = run_one(p)
        new_hit = sorted(codes & set(NEW_CODES))
        exact = bool(stats.get("exact_sbp_outgoing_jasper"))
        if exact:
            exact_total += 1
            if not new_hit:
                exact_clean += 1
        if new_hit:
            any_new += 1
            dirty.append(f"{p.name}: {new_hit} verdict={v}")
    print(f"new HARD on originals: {any_new}/{len(pdfs)}")
    print(f"exact sbp_outgoing clean: {exact_clean}/{exact_total}")
    for line in dirty:
        print(" ", line)

    ok = (
        not miss
        and not miss2
        and any_new == 0
        and exact_clean == exact_total
        and exact_total >= 13
        and len(pdfs) == 22
    )
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
