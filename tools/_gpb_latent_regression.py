"""GPB latent-revision regression.

Expect:
  - 5 GPB originals → Газпромбанк / ЧИСТО / 0 FP
  - 2 Документ-*.pdf → Сбербанк (not GPB)
  - газпромбанк сбп фейк.pdf → ФЕЙК score 95, analysis_complete,
    GPB_LATENT_RECEIPT_REVISION_CONFLICT
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import route

ORIG_DIR = r"C:\Users\fanis\OneDrive\Desktop\чеки\газпромбанк оригинал"
FAKE = r"C:\Users\fanis\OneDrive\Desktop\фейки\газпромбанк сбп фейк.pdf"

GPB_CLEAN = (
    "газпромбанк по карте.pdf",
    "газпромбанк по номеру карты в другой банк.pdf",
    "газпромбанк сбп1.pdf",
    "receipt2211748003420814887.pdf",
    "receipt6206788322134989778.pdf",
)
SBER_ROUTE = (
    "Документ-2026-01-27-015936.pdf",
    "Документ-2026-04-03-150117.pdf",
)


def main() -> int:
    fails: list[str] = []

    for name in GPB_CLEAN:
        path = os.path.join(ORIG_DIR, name)
        bank, r, _ = route(open(path, "rb").read())
        ok = bank == "Газпромбанк" and r.get("verdict") == "ЧИСТО" and not r.get("flags")
        print(f"{'OK' if ok else 'FAIL'} clean {name}: {bank} {r.get('verdict')}")
        if not ok:
            fails.append(name)

    for name in SBER_ROUTE:
        path = os.path.join(ORIG_DIR, name)
        bank, r, _ = route(open(path, "rb").read())
        ok = bank == "Сбербанк"
        print(f"{'OK' if ok else 'FAIL'} sber-route {name}: {bank} {r.get('verdict')}")
        if not ok:
            fails.append(name)

    bank, r, _ = route(open(FAKE, "rb").read())
    d = r.get("details") or {}
    flags = r.get("flags") or []
    latent = any("GPB_LATENT_RECEIPT_REVISION_CONFLICT" in f for f in flags)
    ok = (
        bank == "Газпромбанк"
        and r.get("verdict") == "ФЕЙК"
        and int(r.get("score") or 0) >= 95
        and d.get("analysis_complete") is True
        and latent
    )
    print(
        f"{'OK' if ok else 'FAIL'} fake: {bank} {r.get('verdict')} "
        f"score={r.get('score')} complete={d.get('analysis_complete')} "
        f"latent={latent} eng={d.get('engine')}"
    )
    if not ok:
        fails.append("fake")

    print(f"Result: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
