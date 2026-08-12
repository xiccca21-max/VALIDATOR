"""Sber v1 regression: 22 originals must be ЧИСТО (spec §17 REG-O-001)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.sber_v1.engine import analyze as analyze_v1
from detector.sber_legacy import analyze as analyze_legacy

CORPUS = r"C:\Users\fanis\OneDrive\Desktop\Новая папка (2)"


def main() -> int:
    pdfs = sorted(
        os.path.join(CORPUS, f)
        for f in os.listdir(CORPUS)
        if f.lower().endswith(".pdf")
    )
    print(f"Corpus: {len(pdfs)} PDF in {CORPUS}")
    v1_ok = 0
    legacy_ok = 0
    failures: list[str] = []

    for path in pdfs:
        name = os.path.basename(path)
        data = open(path, "rb").read()
        v1 = analyze_v1(data)
        leg = analyze_legacy(data)
        v1_v = v1.get("verdict")
        leg_v = leg.get("verdict")
        if v1_v == "ЧИСТО":
            v1_ok += 1
        else:
            failures.append(f"V1 FAKE: {name} flags={v1.get('flags')}")
        if leg_v == "ЧИСТО":
            legacy_ok += 1

    print(f"Sber v1:   {v1_ok}/{len(pdfs)} ЧИСТО")
    print(f"Legacy:    {legacy_ok}/{len(pdfs)} ЧИСТО")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("REG-O-001 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
