"""K-TBANK-SBP-PROFILE-EMPIRICAL-001 + ground-truth regression (Jul 2026)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.reputation import file_hash
from detector.tbank import analyze
from detector.tbank_v6.engine import run_pipeline

DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
TG = os.path.join(DOWNLOADS, "Telegram Desktop")

CASES = [
    {
        "path": os.path.join(TG, "receipt_14.07.2026 (8).pdf"),
        "sha": "76d669794ff7395080fdfe32430f8be8970cd90d4e500d21b05ab7e8d563dbc1",
        "ground_truth": "FAKE",
        "expect_verdict": "ФЕЙК",
        "note": "K-TBANK-SBP-CONTROL-LINK-001: control A при triple (6,016,680301)→1",
        "require_flags": ("SBP_CONTROL_TRIPLE_MISMATCH",),
    },
    {
        "path": os.path.join(TG, "receipt_14.07.2026 (13).pdf"),
        "sha": "3ba8b052d596be2306068a7fc4e9587c445f213363a2cbfff207eb9d0e13c1a6",
        "ground_truth": "FAKE",
        "expect_verdict": "ФЕЙК",
        "note": "clone чек39: triple (1,016,680301) требует control 6, не A",
        "require_flags": ("SBP_CONTROL_TRIPLE_MISMATCH",),
    },
    {
        "path": os.path.join(TG, "receipt_14.07.2026 (9).pdf"),
        "sha": "1189dd459ffe2fa1abb113d611ff17bac90cb2701e4b8964b22bc0040ecbcc69",
        "ground_truth": "FAKE",
        "expect_verdict": "ЧИСТО",
        "note": "SBP empirical tier B; ФЕЙК только с 2-й независимой группой",
        "require_flags": ("SBP_PROFILE_EMPIRICAL",),
    },
    {
        "path": os.path.join(DOWNLOADS, "Receipt (1).pdf"),
        "sha": "a786becbf36e74db827a10b91027f66a882c7846bb662d980ab43099ae329034",
        "ground_truth": "ORIGINAL",
        "expect_verdict": "ЧИСТО",
        "forbid_flags": ("SBP_PROFILE_EMPIRICAL",),
    },
    {
        "path": os.path.join(DOWNLOADS, "Receipt (2).pdf"),
        "sha": "9162ae076f5bac70c81679eb31bf09c2bfe8865ab4d5e1c808923d3422a4b87d",
        "ground_truth": "ORIGINAL",
        "expect_verdict": "ЧИСТО",
        "forbid_flags": ("SBP_PROFILE_EMPIRICAL",),
    },
]


def _flag_codes(pipeline) -> set[str]:
    codes: set[str] = set()
    for bucket in (
        pipeline.hard_flags,
        pipeline.known_fake_flags,
        pipeline.supporting_flags,
    ):
        codes.update(f.code for f in bucket)
    return codes


def main() -> int:
    failures: list[str] = []

    for case in CASES:
        path = case["path"]
        name = os.path.basename(path)
        if not os.path.isfile(path):
            failures.append(f"MISSING {name}")
            continue

        data = open(path, "rb").read()
        sha = file_hash(data)
        if sha != case["sha"]:
            failures.append(f"{name}: SHA mismatch got {sha[:16]} expected {case['sha'][:16]}")

        result = analyze(data, sha)
        pipeline = run_pipeline(data, sha)
        codes = _flag_codes(pipeline)
        verdict = result.get("verdict")

        if case.get("expect_verdict") and verdict != case["expect_verdict"]:
            failures.append(
                f"{name}: verdict={verdict!r} expected {case['expect_verdict']!r} "
                f"(gt={case['ground_truth']})"
            )

        for code in case.get("require_flags", ()):
            if code not in codes:
                failures.append(f"{name}: missing required flag {code} (gt={case['ground_truth']})")

        for code in case.get("forbid_flags", ()):
            if code in codes:
                failures.append(f"{name}: forbidden flag {code} (gt={case['ground_truth']})")

    if failures:
        print("FAIL", len(failures))
        for item in failures:
            print(" ", item)
        return 1

    print("PASS empirical regression (5 cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
