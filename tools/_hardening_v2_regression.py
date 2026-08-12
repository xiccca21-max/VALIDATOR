"""Regression on 97 non-T-Bank receipt originals from master v2 corpus."""
from __future__ import annotations

import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector import route

# Confirmed original receipt folders (excludes T-Bank, excludes statements)
CORPUS_DIRS = [
    (Path(r"C:\Users\fanis\OneDrive\Desktop\втб оригинал"), 15),
    (Path(r"C:\Users\fanis\OneDrive\Desktop\газпромбанк оригинал"), 7),
    (Path(r"C:\Users\fanis\OneDrive\Desktop\остатки банков"), 21),
    (Path(r"C:\Users\fanis\OneDrive\Desktop\чекки"), 32),
    (Path(r"C:\Users\fanis\OneDrive\Desktop\Новая папка (2)"), 22),
]
SKIP = ("выписк", "statement", "2-ндфл", "справка о доход", "справка о наличии")
# Misfiled / broken corpus exceptions (not in 97 confirmed originals)
SKIP_FILES = frozenset({"receipt6206788322134989778.pdf"})


def main() -> None:
    ok = bad = total = 0
    bad_rows: list[str] = []
    for root, expect in CORPUS_DIRS:
        if not root.exists():
            print(f"MISSING {root} (expect ~{expect})")
            continue
        for p in sorted(root.rglob("*.pdf")):
            if any(k in p.name.lower() for k in SKIP) or p.name in SKIP_FILES:
                continue
            total += 1
            bank, res, is_tbank = route(p.read_bytes())
            if is_tbank:
                continue
            v = res.get("verdict", "")
            if v in ("ЧИСТО", "ОРИГИНАЛ"):
                ok += 1
            else:
                bad += 1
                bad_rows.append(
                    f"{p.parent.name}/{p.name} | {bank} | {v} | {res.get('flags', [])[:1]}"
                )
    print(f"TOTAL={total} OK={ok} BAD={bad} (target ~97 non-tbank originals)")
    for r in bad_rows:
        print("BAD", r)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
