"""Stable adapters around the validator's production and structural APIs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Verdict(str, Enum):
    FAKE = "FAKE"
    CLEAN = "CLEAN"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PdfCheckResult:
    bank: str
    verdict: Verdict
    raw_verdict: str
    score: int
    flags: tuple[str, ...]
    is_tbank: bool
    sha256: str
    details: dict[str, Any]


@dataclass(frozen=True)
class StructuralCheckResult:
    all_codes: frozenset[str]
    hard_codes: frozenset[str]
    diagnostic_codes: frozenset[str]
    error: str | None = None


def normalize_verdict(raw: str) -> Verdict:
    value = (raw or "").strip().upper()
    if value in {"ФЕЙК", "FAKE"}:
        return Verdict.FAKE
    if value in {"ЧИСТО", "ОРИГИНАЛ", "CLEAN", "ORIGINAL"}:
        return Verdict.CLEAN
    if "НЕИЗВЕСТ" in value or value == "UNKNOWN":
        return Verdict.UNKNOWN
    return Verdict.UNKNOWN


def check_pdf_bytes(pdf_bytes: bytes) -> PdfCheckResult:
    """Run the same top-level route used by the bot."""
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    try:
        from detector import route

        bank, result, is_tbank = route(pdf_bytes)
    except Exception as exc:  # The arena must record crashes, not hide them.
        return PdfCheckResult(
            bank="",
            verdict=Verdict.ERROR,
            raw_verdict="ERROR",
            score=0,
            flags=(f"[ANALYSIS_NOT_COMPLETED] {exc}",),
            is_tbank=False,
            sha256=sha256,
            details={"analysis_complete": False, "error": str(exc)},
        )

    details = dict(result.get("details") or {})
    raw_verdict = str(result.get("verdict") or "")
    return PdfCheckResult(
        bank=str(bank),
        verdict=normalize_verdict(raw_verdict),
        raw_verdict=raw_verdict,
        score=int(result.get("score") or 0),
        flags=tuple(str(flag) for flag in (result.get("flags") or ())),
        is_tbank=bool(is_tbank),
        sha256=sha256,
        details=details,
    )


def check_pdf_path(path: str | Path) -> PdfCheckResult:
    return check_pdf_bytes(Path(path).read_bytes())


def check_structural_bytes(pdf_bytes: bytes) -> StructuralCheckResult:
    """Run the low-level audit without turning diagnostics into user verdicts."""
    try:
        from detector.structural_deep import run_structural_deep_audit

        result = run_structural_deep_audit(pdf_bytes)
        hard = frozenset(item.code for item in result.hard_findings)
        diagnostic = frozenset(item.code for item in result.diagnostic_findings)
        all_codes = frozenset(item.code for item in result.findings)
        return StructuralCheckResult(all_codes, hard, diagnostic)
    except Exception as exc:
        return StructuralCheckResult(
            frozenset(), frozenset(), frozenset(), error=str(exc)
        )
