from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from detector.alfa_v2 import analyze


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "analysis" / "bankpdf_history_dataset.json"
OUTPUT = ROOT / "analysis" / "bankpdf_rule_matrix.json"
CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]")


def rule_codes(result: dict[str, Any]) -> set[str]:
    details = result.get("details") or {}
    values = list(details.get("hard_flags") or []) + list(details.get("ignored_observations") or [])
    codes = set()
    for value in values:
        match = CODE_RE.match(str(value))
        if match:
            codes.add(match.group(1))
    return codes


def odds_ratio(pass_with: int, fail_with: int, pass_without: int, fail_without: int) -> float:
    return ((fail_with + 0.5) * (pass_without + 0.5)) / (
        (pass_with + 0.5) * (fail_without + 0.5)
    )


def main() -> None:
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if (
            row.get("bytes_reliable")
            and row.get("pdf_sha")
            and row.get("pdf_exists")
            and not row.get("reuse_notice")
        ):
            grouped[row["pdf_sha"]].append(row)

    samples: list[dict[str, Any]] = []
    excluded_conflicts: list[dict[str, Any]] = []
    for digest, members in grouped.items():
        verdicts = {member["verdict"] for member in members}
        if len(verdicts) != 1:
            excluded_conflicts.append(
                {
                    "pdf_sha": digest,
                    "events": [
                        {
                            "filename": member["filename"],
                            "verdict": member["verdict"],
                            "sent_at": member["sent_at"],
                        }
                        for member in members
                    ],
                }
            )
            continue
        row = members[0]
        path = Path(row["source_pdf_path"])
        result = analyze(path.read_bytes())
        samples.append(
            {
                "pdf_sha": digest,
                "filename": row["filename"],
                "verdict": row["verdict"],
                "rules": sorted(rule_codes(result)),
            }
        )

    total_pass = sum(sample["verdict"] == "PASS" for sample in samples)
    total_fail = sum(sample["verdict"] == "FAIL" for sample in samples)
    rule_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for sample in samples:
        for code in sample["rules"]:
            if "IDENTITY" not in code:
                rule_counts[code][sample["verdict"]] += 1

    ranking = []
    for code, counts in rule_counts.items():
        pass_with = counts["PASS"]
        fail_with = counts["FAIL"]
        support = pass_with + fail_with
        pass_without = total_pass - pass_with
        fail_without = total_fail - fail_with
        if support < 3:
            continue
        with_fail_rate = fail_with / support
        without_total = pass_without + fail_without
        without_fail_rate = fail_without / without_total if without_total else math.nan
        ranking.append(
            {
                "rule": code,
                "support": support,
                "pass_with": pass_with,
                "fail_with": fail_with,
                "fail_rate_with": with_fail_rate,
                "fail_rate_without": without_fail_rate,
                "fail_rate_delta": with_fail_rate - without_fail_rate,
                "fail_odds_ratio_smoothed": odds_ratio(
                    pass_with, fail_with, pass_without, fail_without
                ),
                "perfect_fail_separator": pass_with == 0,
                "perfect_pass_separator": fail_with == 0,
            }
        )
    ranking.sort(
        key=lambda item: (
            not item["perfect_fail_separator"],
            -item["fail_rate_delta"],
            -item["support"],
        )
    )
    output = {
        "samples": len(samples),
        "passes": total_pass,
        "fails": total_fail,
        "excluded_conflicting_sha": excluded_conflicts,
        "ranking": ranking,
        "sample_rules": samples,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "samples": len(samples),
                "passes": total_pass,
                "fails": total_fail,
                "excluded_conflicting_sha": len(excluded_conflicts),
                "top_rules": ranking[:30],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
