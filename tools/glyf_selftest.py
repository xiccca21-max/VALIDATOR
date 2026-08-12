#!/usr/bin/env python3
"""Generator self-test: exit 0 if PDF passes glyf fingerprint reference."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.glyf_fingerprint import assert_glyf_ok, run_glyf_checks


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/glyf_selftest.py path/to/receipt.pdf")
        sys.exit(2)
    pdf = Path(sys.argv[1]).read_bytes()
    result = run_glyf_checks(pdf)
    if result.flags:
        for f in result.flags:
            print(f"FAIL [{f.code}] {f.detail}")
        sys.exit(1)
    print("OK glyf fingerprint")
    try:
        assert_glyf_ok(pdf)
    except ValueError as e:
        print(f"FAIL {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
