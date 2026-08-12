"""VTB v2 binary verdict (future-safe T-Bank model)."""

from __future__ import annotations

from .rules import HARD_CODES, KNOWN_FAKE_CODES, SUPPORTING_GROUPS
from .types import PipelineResult, VtbFlag

FAKE_THRESHOLD = 60


def distinct_supporting_groups(flags: list[VtbFlag]) -> set[str]:
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
            "[ANALYSIS_NOT_COMPLETED] полный VTB v2 pipeline не завершён",
        ]

    if result.not_vtb_receipt:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[NOT_VTB_RECEIPT] файл не является квитанцией ВТБ",
        ]

    decisive = _decisive_evidence(result)
    if decisive:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, decisive

    if result.cross_document_identity_conflict:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[VTB_CROSS_DOCUMENT_IDENTITY_CONFLICT] идентификатор конфликтует "
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

    return "ЧИСТО", "✅", 0, []


def ingest_flag(result: PipelineResult, flag: VtbFlag) -> None:
    explicit = (flag.tier or "").upper()
    if explicit in {"DIAGNOSTIC", "IGNORE", "IGNORED"}:
        result.ignored_observations.append(flag.format())
        return
    if flag.code in KNOWN_FAKE_CODES or explicit == "KNOWN":
        flag.tier = "KNOWN"
        # Deduplicate alternative matchers of the same fake series.
        if any(f.code == flag.code for f in result.known_fake_flags):
            return
        result.known_fake_flags.append(flag)
        return
    if flag.code in HARD_CODES or explicit in {"HARD", "A"}:
        flag.tier = "HARD"
        if flag.code in {
            "VTB_METHOD_SBP_TO_SELF_BANK",
            "VTB_METHOD_FIELDSET_COLLISION",
        }:
            flag.group = flag.group or "semantic_method"
        result.hard_flags.append(flag)
        return
    if flag.code in SUPPORTING_GROUPS or explicit == "B":
        flag.tier = "B"
        flag.group = flag.group or SUPPORTING_GROUPS.get(flag.code, "")
        result.supporting_flags.append(flag)
        return
    result.ignored_observations.append(flag.format())
