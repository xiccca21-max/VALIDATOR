"""Ozon v1 regression: 32 originals must be ЧИСТО (spec OZ-REG-O-001)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.ozon_v1.engine import analyze as analyze_v1
from detector.ozon_legacy import analyze as analyze_legacy

CORPUS = r"C:\Users\fanis\OneDrive\Desktop\озон чекии"


def main() -> int:
    pdfs = sorted(
        os.path.join(CORPUS, f)
        for f in os.listdir(CORPUS)
        if f.lower().endswith(".pdf")
    )
    print(f"Corpus: {len(pdfs)} PDF")
    v1_ok = 0
    legacy_ok = 0
    failures: list[str] = []

    for path in pdfs:
        name = os.path.basename(path)
        data = open(path, "rb").read()
        v1 = analyze_v1(data)
        leg = analyze_legacy(data)
        if v1.get("verdict") == "ЧИСТО":
            v1_ok += 1
        else:
            failures.append(
                f"V1 FAKE: {name} | family={v1.get('details',{}).get('family')} "
                f"flags={v1.get('flags')}"
            )
        if leg.get("verdict") == "ЧИСТО":
            legacy_ok += 1

    print(f"Ozon v1:   {v1_ok}/{len(pdfs)} ЧИСТО")
    print(f"Legacy:    {legacy_ok}/{len(pdfs)} ЧИСТО")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("OZ-REG-O-001 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
