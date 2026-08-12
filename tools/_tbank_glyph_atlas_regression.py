"""K-TBANK-GLYPH-ATLAS-001 regression — originals clean, no SHA-based false positives."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.reputation import file_hash
from detector.tbank import analyze
from detector.tbank_glyph_atlas import check_tbank_glyph_atlas
from detector.tbank_v6.engine import run_pipeline

DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
TG = os.path.join(DOWNLOADS, "Telegram Desktop")

ORIGINALS = [
    (os.path.join(DOWNLOADS, "Receipt (1).pdf"), "a786becbf36e74db827a10b91027f66a882c7846bb662d980ab43099ae329034"),
    (os.path.join(DOWNLOADS, "Receipt (2).pdf"), "9162ae076f5bac70c81679eb31bf09c2bfe8865ab4d5e1c808923d3422a4b87d"),
]

FAKES = [
    (os.path.join(TG, "receipt_14.07.2026 (8).pdf"), "76d669794ff7395080fdfe32430f8be8970cd90d4e500d21b05ab7e8d563dbc1"),
    (os.path.join(TG, "receipt_14.07.2026 (9).pdf"), "1189dd459ffe2fa1abb113d611ff17bac90cb2701e4b8964b22bc0040ecbcc69"),
]

FORBIDDEN_ATLAS_FLAGS = frozenset({
    "FONTFILE2_UNKNOWN",
    "GLYF_POOL_MISS",
    "UNKNOWN_SUBSET_SHA",
})


def main() -> int:
    failures: list[str] = []

    for path, sha in ORIGINALS:
        if not os.path.isfile(path):
            failures.append(f"MISSING {path}")
            continue
        data = open(path, "rb").read()
        if file_hash(data) != sha:
            failures.append(f"SHA mismatch {os.path.basename(path)}")
        r = analyze(data, sha)
        atlas = check_tbank_glyph_atlas(data)
        hard_atlas = [f.code for f in atlas.flags]
        if r.get("verdict") != "ЧИСТО":
            failures.append(f"ORIGINAL {os.path.basename(path)} verdict={r.get('verdict')} flags={r.get('flags', [])[:3]}")
        if hard_atlas:
            failures.append(f"ORIGINAL {os.path.basename(path)} atlas_hard={hard_atlas}")

    for path, sha in FAKES:
        if not os.path.isfile(path):
            failures.append(f"MISSING {path}")
            continue
        data = open(path, "rb").read()
        if file_hash(data) != sha:
            failures.append(f"SHA mismatch {os.path.basename(path)}")
        atlas = check_tbank_glyph_atlas(data)
        for code in [f.code for f in atlas.flags]:
            if code in FORBIDDEN_ATLAS_FLAGS:
                failures.append(f"FAKE {os.path.basename(path)} forbidden flag {code}")
        pipe = run_pipeline(data, sha)
        ff2_flags = [
            f.code for f in pipe.hard_flags
            if "FONT" in f.code and "SHA" in f.detail.upper()
        ]
        if ff2_flags:
            failures.append(f"FAKE {os.path.basename(path)} false FF2 hard {ff2_flags}")

    if failures:
        print("FAIL", len(failures))
        for f in failures:
            print(" ", f)
        return 1
    print("PASS glyph atlas regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
