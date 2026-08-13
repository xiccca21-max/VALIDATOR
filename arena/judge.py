"""Deterministic scoring; agents cannot alter acceptance decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapter import Verdict, check_pdf_bytes, check_structural_bytes
from .synthetic import build_pdf


def evaluate_candidate(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pdf_path = manifest_path.with_name(str(manifest["file"]))
    pdf_bytes = pdf_path.read_bytes()
    structural = check_structural_bytes(pdf_bytes)
    production = check_pdf_bytes(pdf_bytes)
    expected = set(str(code) for code in manifest["expected_codes"])
    caught = not structural.error and expected.issubset(structural.all_codes)
    promoted = bool(expected) and expected.issubset(structural.hard_codes)
    return {
        "manifest": str(manifest_path),
        "file": str(pdf_path),
        "sha256": manifest["sha256"],
        "mutations": manifest["mutations"],
        "signature": manifest["signature"],
        "expected_codes": sorted(expected),
        "observed_codes": sorted(structural.all_codes),
        "hard_codes": sorted(structural.hard_codes),
        "diagnostic_codes": sorted(structural.diagnostic_codes),
        "caught": caught,
        "promoted_to_hard": promoted,
        "structural_error": structural.error,
        "production_verdict": production.verdict.value,
        "raw_verdict": production.raw_verdict,
        "production_error": (
            production.details.get("error")
            if production.verdict is Verdict.ERROR
            else None
        ),
    }


def smoke_benign() -> dict[str, Any]:
    pdf_bytes = build_pdf()
    structural = check_structural_bytes(pdf_bytes)
    production = check_pdf_bytes(pdf_bytes)
    return {
        "ok": not structural.error
        and not structural.all_codes
        and production.verdict is not Verdict.ERROR,
        "structural_codes": sorted(structural.all_codes),
        "structural_error": structural.error,
        "production_verdict": production.verdict.value,
        "production_error": production.details.get("error"),
    }


def score_round(evaluations: list[dict[str, Any]], benign: dict[str, Any]) -> int:
    score = 0
    for item in evaluations:
        score += 10 if item["caught"] else -10
        if item["promoted_to_hard"]:
            score += 3
        if item["structural_error"] or item["production_error"]:
            score -= 50
    if not benign["ok"]:
        score -= 100
    return score
