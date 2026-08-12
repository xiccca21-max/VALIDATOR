"""Quick regression: SBP_CIPHER and any forgery flag must yield FAKE."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.verdict import finalize_verdict, is_forgery_flag

CASES = [
    (["[SBP_CIPHER_STRUCTURE] позиция 17"], "ФЕЙК"),
    (["[SBP_CIPHER_MISSING] не найден id"], "ФЕЙК"),
    (["[FF2_SUBSET_UNKNOWN] не в корпусе"], "ЧИСТО"),
    (["[TBANK_F1_HMTX_DRIFT] дрейф"], "ЧИСТО"),
    (["[AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS] x"], "ФЕЙК"),
    ([], "ЧИСТО"),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ok = 0
    for flags, want in CASES:
        verdict, _, score, forgery = finalize_verdict(0, flags)
        got = verdict
        status = "OK" if got == want else "FAIL"
        if got == want:
            ok += 1
        print(f"{status} want={want} got={got} score={score} flags={flags[:1]}")
    print(f"\n{ok}/{len(CASES)} passed")
    if ok != len(CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
