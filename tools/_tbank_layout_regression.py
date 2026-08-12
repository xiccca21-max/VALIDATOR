"""T-Bank layout regression — Receipt (1)/(2) + corpus must stay ЧИСТО."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.tbank import analyze
from detector.reputation import file_hash

ORIGINALS = [
    r"C:\Users\fanis\Downloads\Receipt (1).pdf",
    r"C:\Users\fanis\Downloads\Receipt (2).pdf",
]
CORPUS = r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк"


def main() -> int:
    failures: list[str] = []
    for path in ORIGINALS:
        if not os.path.isfile(path):
            failures.append(f"MISSING {path}")
            continue
        data = open(path, "rb").read()
        r = analyze(data, file_hash(data))
        if r.get("verdict") != "ЧИСТО":
            failures.append(f"{os.path.basename(path)}: {r.get('verdict')} {r.get('flags', [])[:3]}")

    if os.path.isdir(CORPUS):
        for name in sorted(os.listdir(CORPUS)):
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(CORPUS, name)
            data = open(path, "rb").read()
            r = analyze(data, file_hash(data))
            if r.get("verdict") != "ЧИСТО":
                failures.append(f"corpus/{name}: {r.get('verdict')} layout={[f for f in r.get('flags',[]) if 'LAYOUT' in f][:2]}")

    if failures:
        print("FAIL", len(failures))
        for f in failures[:20]:
            print(" ", f)
        return 1
    print("PASS layout regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
