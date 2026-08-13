"""Zero-FP gate for structural_deep codes + deepened xref_integrity.

Scans genuine PDFs under Desktop/чеки. Prints per-code hit counts.
Does NOT mutate ENABLED_STRUCTURAL_HARD unless --enable-safe is passed.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.structural_deep import ALL_NEW_STRUCTURAL_CODES, run_structural_deep_audit
from detector.structure import xref_integrity
from detector.structural_deep_xref_stream import set_enabled_structural_hard


def main() -> int:
    pdfs = sorted(ROOT.rglob("*.pdf"))
    print(f"GENUINE_PDFS {len(pdfs)} root={ROOT}", flush=True)
    deep_hits: Counter[str] = Counter()
    xref_broken = 0
    xref_details: list[str] = []
    errors = 0
    for i, p in enumerate(pdfs, 1):
        try:
            data = p.read_bytes()
        except Exception as e:
            errors += 1
            print(f"READ_ERR {p} {e!r}", flush=True)
            continue
        try:
            broken, detail = xref_integrity(data)
            if broken:
                xref_broken += 1
                if len(xref_details) < 25:
                    xref_details.append(f"{p.relative_to(ROOT)} :: {detail}")
            res = run_structural_deep_audit(data)
            for f in res.findings:
                if f.code in ALL_NEW_STRUCTURAL_CODES or f.code == "XREF_OFFSET_INVALID":
                    deep_hits[f.code] += 1
        except Exception as e:
            errors += 1
            print(f"AUDIT_ERR {p.relative_to(ROOT)} {e!r}", flush=True)
        if i % 50 == 0:
            print(f"PROGRESS {i}/{len(pdfs)} xref_broken={xref_broken}", flush=True)

    print("==== XREF_INTEGRITY_BROKEN", xref_broken, "====", flush=True)
    for d in xref_details:
        print("XREF_SAMPLE", d, flush=True)
    print("==== DEEP_CODE_HITS ====", flush=True)
    for code, n in sorted(deep_hits.items(), key=lambda x: (-x[1], x[0])):
        print(f"{code}\t{n}", flush=True)

    safe = sorted(
        c for c in ALL_NEW_STRUCTURAL_CODES
        if deep_hits.get(c, 0) == 0
    )
    unsafe = sorted(
        c for c in ALL_NEW_STRUCTURAL_CODES
        if deep_hits.get(c, 0) > 0
    )
    print("SAFE_ZERO_FP", ",".join(safe), flush=True)
    print("UNSAFE_HAS_FP", ",".join(f"{c}:{deep_hits[c]}" for c in unsafe), flush=True)
    print("ERRORS", errors, flush=True)

    if "--enable-safe" in sys.argv:
        # Never auto-enable SFNT checksum/adjustment — known genuine drift.
        block = {
            "SFNT_TABLE_CHECKSUM_INVALID",
            "SFNT_CHECKSUM_ADJUSTMENT_INVALID",
            "SFNT_DIRECTORY_CONTRADICTION",
        }
        enable = frozenset(c for c in safe if c not in block)
        set_enabled_structural_hard(enable)
        # Persist into module file by printing recommendation
        print("ENABLE_RECOMMEND", sorted(enable), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
