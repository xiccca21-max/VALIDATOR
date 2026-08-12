"""Regression REG-O-001 for Alfa v1.0 (40 originals)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.alfa_v1.engine import VALIDATOR_VERSION, analyze

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")


def main() -> None:
    print("validator", VALIDATOR_VERSION)
    if not CORPUS.exists():
        print("CORPUS MISSING", CORPUS)
        return
    pdfs = sorted(CORPUS.glob("*.pdf"))
    print("files", len(pdfs))
    fp = 0
    for p in pdfs:
        r = analyze(p.read_bytes())
        if r["verdict"] != "ЧИСТО":
            fp += 1
            print("FP", p.name, r["verdict"], r["flags"][:3])
    print(f"REG-O-001: {len(pdfs) - fp}/{len(pdfs)} ОРИГИНАЛ, FP={fp}")

    # shadow comparison sample
    os.environ["ALFA_V1_ROLLOUT"] = "shadow"
    from detector.alfa import analyze as routed
    mism = 0
    for p in pdfs[:5]:
        r = routed(p.read_bytes())
        sh = (r.get("details") or {}).get("alfa_v1_shadow") or {}
        if sh and not sh.get("match"):
            mism += 1
    print("shadow sample mismatches (first 5):", mism)


if __name__ == "__main__":
    main()
