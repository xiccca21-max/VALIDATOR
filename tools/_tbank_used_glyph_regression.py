"""A-FONT-USED-CID-EMPTY-GLYPH-001 regression — test_sbp_10 + corpus originals."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.reputation import file_hash
from detector.tbank import analyze

TEST_DIR = os.path.join(
    os.environ.get("USERPROFILE", ""),
    "OneDrive",
    "Desktop",
    "ЗАПАСКА 13.07.26",
    "output",
    "test_sbp_10",
)

FAKE_EXPECT = {
    "receipt_14_07_2026_02_zhuravlev.pdf": ("ФЕЙК", ("GLYPH_SLOT_TRANSPLANT",)),
    "receipt_14_07_2026_08_tsypin.pdf": ("ФЕЙК", ("GLYPH_SLOT_TRANSPLANT",)),
}

ORIGINAL_EXPECT = {
    "receipt_14_07_2026_01_alekseev.pdf": "ЧИСТО",
    "receipt_14_07_2026_03_shchukin.pdf": "ЧИСТО",
    "receipt_14_07_2026_04_yusupov.pdf": "ЧИСТО",
    "receipt_14_07_2026_05_khromov.pdf": "ЧИСТО",
    "receipt_14_07_2026_06_fyodorov.pdf": "ЧИСТО",
    "receipt_14_07_2026_07_egorova.pdf": "ЧИСТО",
}

CORPUS_DIRS = [
    os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop", "чеки", "т банк"),
]


def _codes(result: dict) -> set[str]:
    codes: set[str] = set()
    for f in result.get("flags", []):
        if f.startswith("["):
            codes.add(f.split("]", 1)[0][1:])
    return codes


def main() -> int:
    failures: list[str] = []

    if not os.path.isdir(TEST_DIR):
        failures.append(f"MISSING test dir {TEST_DIR}")
    else:
        for name, (exp_verdict, req_flags) in FAKE_EXPECT.items():
            path = os.path.join(TEST_DIR, name)
            if not os.path.isfile(path):
                failures.append(f"MISSING {name}")
                continue
            data = open(path, "rb").read()
            r = analyze(data, file_hash(data))
            if r.get("verdict") != exp_verdict:
                failures.append(f"{name}: verdict={r.get('verdict')!r} expected {exp_verdict}")
            codes = _codes(r)
            for code in req_flags:
                if code not in codes:
                    failures.append(f"{name}: missing flag {code} got {sorted(codes)[:5]}")

        for name, exp_verdict in ORIGINAL_EXPECT.items():
            path = os.path.join(TEST_DIR, name)
            if not os.path.isfile(path):
                failures.append(f"MISSING {name}")
                continue
            data = open(path, "rb").read()
            r = analyze(data, file_hash(data))
            if r.get("verdict") != exp_verdict:
                failures.append(
                    f"{name}: verdict={r.get('verdict')!r} expected {exp_verdict} "
                    f"flags={r.get('flags', [])[:3]}"
                )
            if "USED_CID_EMPTY_GLYPH" in _codes(r):
                failures.append(f"{name}: forbidden USED_CID_EMPTY_GLYPH")

    corpus_n = 0
    for corpus in CORPUS_DIRS:
        if not os.path.isdir(corpus):
            continue
        for name in sorted(os.listdir(corpus)):
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(corpus, name)
            data = open(path, "rb").read()
            r = analyze(data, file_hash(data))
            corpus_n += 1
            if r.get("verdict") != "ЧИСТО":
                failures.append(f"corpus/{name}: {r.get('verdict')} flags={r.get('flags', [])[:2]}")
            elif "USED_CID_EMPTY_GLYPH" in _codes(r) or "TBANK_TEXT_GLYPH_PARITY" in _codes(r):
                failures.append(f"corpus/{name}: forbidden glyph integrity flags")
            elif "GLYPH_SLOT_TRANSPLANT" in _codes(r):
                failures.append(f"corpus/{name}: forbidden GLYPH_SLOT_TRANSPLANT")

    if corpus_n < 50:
        failures.append(f"corpus too small: {corpus_n} pdfs")

    if failures:
        print("FAIL", len(failures))
        for item in failures[:30]:
            print(" ", item)
        return 1

    print(
        f"PASS used-cid-empty-glyph regression "
        f"({len(FAKE_EXPECT)} fakes, {len(ORIGINAL_EXPECT)} test originals, {corpus_n} corpus)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
