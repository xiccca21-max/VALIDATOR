#!/usr/bin/env python3
"""Fast targeted stream serializer check — no full corpus."""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import analyze
from detector.tbank_flate_profile import enumerate_flate_streams
from detector.tbank_stream_serializer import check_mixed_flate_serializer, profiles_table

TOUGH = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026.pdf")
FAKE = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026 (4).pdf")


def find_fake() -> Path | None:
    if FAKE.exists():
        return FAKE
    for base in (Path(r"C:\Users\fanis\Downloads"), ROOT, Path(r"C:\Users\fanis\OneDrive\Desktop")):
        if not base.exists():
            continue
        for f in base.glob("**/receipt_13.07.2026*.pdf"):
            if "(4)" in f.name:
                return f
    return None


def table(path: Path, label: str) -> None:
    print(f"\n=== {label}: {path.name} ===")
    b = path.read_bytes()
    profs = enumerate_flate_streams(b)
    print(f"streams: {len(profs)}")
    for row in profiles_table(profs):
        print(
            f"  {row['object']:>6}  {row['role']:14}  "
            f"canonical={str(row['canonical_match']):5}  "
            f"actual={row['actual_hash']}  expected={row['expected_hash']}"
        )
    sr = check_mixed_flate_serializer(b)
    r = analyze(b)
    print(f"serializer: {sr.stats.get('verdict', sr.stats.get('skipped'))}")
    print(f"hard: {bool(sr.hard_flags)}")
    print(f"analyze verdict: {r['verdict']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fake = find_fake()
    if fake:
        table(fake, "FAKE anchor")
    else:
        print("FAKE anchor MISSING:", FAKE)

    if TOUGH.exists():
        table(TOUGH, "TOUGH original")
    else:
        print("TOUGH MISSING:", TOUGH)


if __name__ == "__main__":
    main()
