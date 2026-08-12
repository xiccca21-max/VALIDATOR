"""Sber v2 binary verdict: HARD/KNOWN/≥2 Tier-B/UNKNOWN/CLEAN."""

from __future__ import annotations

from .rules import HARD_CODES, KNOWN_FAKE_CODES, SUPPORTING_GROUPS
from .types import PipelineResult, SberFlag

FAKE_THRESHOLD = 60


def distinct_supporting_groups(flags: list[SberFlag]) -> set[str]:
    groups: set[str] = set()
    for flag in flags:
        if flag.tier != "B":
            continue
        grp = flag.group or SUPPORTING_GROUPS.get(flag.code, "")
        if grp:
            groups.add(grp)
    return groups


def _decisive_evidence(result: PipelineResult) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for flag in result.known_fake_flags + result.hard_flags:
        line = flag.format()
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def compute_verdict(result: PipelineResult) -> tuple[str, str, int, list[str]]:
    if not result.analysis_complete:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[ANALYSIS_NOT_COMPLETED] полный Sber v2 pipeline не завершён",
        ]

    if result.not_sber_receipt:
        return "НЕИЗВЕСТНЫЙ ДОКУМЕНТ", "⚪", 0, [
            "[NOT_SBER_RECEIPT] неизвестный банк",
        ]

    decisive = _decisive_evidence(result)
    if decisive:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, decisive

    if result.cross_document_identity_conflict:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[SBER_CROSS_DOCUMENT_IDENTITY_CONFLICT] идентификатор конфликтует "
            "с реквизитами другого документа",
        ]

    groups = distinct_supporting_groups(result.supporting_flags)
    if len(groups) >= 2:
        return (
            "ФЕЙК",
            "🔴",
            FAKE_THRESHOLD,
            [f.format() for f in result.supporting_flags if f.tier == "B"],
        )

    if result.new_coherent_profile:
        return "НЕИЗВЕСТНЫЙ ДОКУМЕНТ", "⚪", 0, [
            "[SBER_NEW_COHERENT_PROFILE] целостный неизвестный профиль без "
            "внутренних противоречий",
        ]

    return "ЧИСТО", "✅", 0, []


def ingest_flag(result: PipelineResult, flag: SberFlag) -> None:
    from .rules import IGNORED_CODES

    explicit = (flag.tier or "").upper()
    if flag.code in IGNORED_CODES or explicit in {"DIAGNOSTIC", "IGNORE", "IGNORED"}:
        result.ignored_observations.append(flag.format())
        return
    if flag.code in KNOWN_FAKE_CODES or explicit == "KNOWN":
        flag.tier = "KNOWN"
        result.known_fake_flags.append(flag)
        return
    if flag.code in HARD_CODES or explicit in {"HARD", "A"}:
        flag.tier = "HARD"
        result.hard_flags.append(flag)
        return
    if flag.code in SUPPORTING_GROUPS or explicit == "B":
        flag.tier = "B"
        flag.group = flag.group or SUPPORTING_GROUPS.get(flag.code, "")
        result.supporting_flags.append(flag)
        return
    result.ignored_observations.append(flag.format())
