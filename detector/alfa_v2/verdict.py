"""Alfa v2 binary verdict policy."""

from __future__ import annotations

from .rules import (
    HARD_CODES,
    IGNORED_CODES,
    KNOWN_FAKE_CODES,
    SUPPORTING_GROUPS,
    classify_code,
)
from .types import AlfaFlag, PipelineResult

FAKE_THRESHOLD = 60


def distinct_supporting_groups(flags: list[AlfaFlag]) -> set[str]:
    return {
        flag.group or SUPPORTING_GROUPS.get(flag.code, "")
        for flag in flags
        if (flag.group or SUPPORTING_GROUPS.get(flag.code, ""))
    }


def _formatted_unique(flags: list[AlfaFlag]) -> list[str]:
    seen: set[str] = set()
    evidence: list[str] = []
    for flag in flags:
        line = flag.format()
        if line not in seen:
            seen.add(line)
            evidence.append(line)
    return evidence


def compute_verdict(result: PipelineResult) -> tuple[str, str, int, list[str]]:
    """Return the stable response tuple used by the detector dispatcher."""

    if not result.analysis_complete:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[ANALYSIS_NOT_COMPLETED] полный Alfa v2 pipeline не завершён",
        ]

    if result.not_alfa_receipt:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[NOT_ALFA_RECEIPT] файл не является квитанцией Альфа-Банка",
        ]

    decisive = _formatted_unique(result.known_fake_flags + result.hard_flags)
    if decisive:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, decisive

    if result.cross_document_identity_conflict:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[ALFA_OPERATION_IDENTITY_CONFLICT] идентификатор операции "
            "конфликтует с реквизитами другого документа",
        ]

    groups = distinct_supporting_groups(result.supporting_flags)
    if len(groups) >= 2:
        return (
            "ФЕЙК",
            "🔴",
            FAKE_THRESHOLD,
            _formatted_unique(result.supporting_flags),
        )

    if result.manual_review_required or result.manual_review_flags:
        return (
            "НЕИЗВЕСТНЫЙ ДОКУМЕНТ",
            "⚪",
            0,
            _formatted_unique(result.manual_review_flags),
        )

    # No supporting group, or exactly one group, is clean by policy.
    return "ЧИСТО", "✅", 0, []


def ingest_flag(result: PipelineResult, flag: AlfaFlag) -> None:
    """Place a stage observation into its policy-controlled evidence channel."""

    classification = classify_code(flag.code)
    explicit_tier = flag.tier.upper()

    # Demoted / novelty codes and explicit DIAGNOSTIC never decide FAKE,
    # even if an emitter still tags them HARD/A.
    if (
        classification == "IGNORE"
        or flag.code in IGNORED_CODES
        or explicit_tier in {"DIAGNOSTIC", "IGNORE", "IGNORED"}
    ):
        result.ignored_observations.append(flag.format())
        return

    if explicit_tier == "MANUAL":
        result.manual_review_required = True
        result.manual_review_flags.append(flag)
        return

    if classification == "KNOWN" or explicit_tier == "KNOWN":
        flag.tier = "KNOWN"
        result.known_fake_flags.append(flag)
    elif classification == "HARD" or (
        explicit_tier in {"HARD", "A"} and flag.code not in SUPPORTING_GROUPS
    ):
        flag.tier = "HARD"
        result.hard_flags.append(flag)
    elif classification == "B" or explicit_tier == "B":
        flag.tier = "B"
        flag.group = flag.group or SUPPORTING_GROUPS.get(flag.code, "")
        result.supporting_flags.append(flag)
    else:
        result.ignored_observations.append(flag.format())
