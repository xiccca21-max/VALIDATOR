"""v6.0 binary verdict engine (spec section 3)."""

from __future__ import annotations

from .rules import HARD_CODES, IGNORED_CODES, KNOWN_FAKE_CODES, SUPPORTING_GROUPS
from .types import PipelineResult, V6Flag

FAKE_THRESHOLD = 60


def _distinct_supporting_groups(flags: list[V6Flag]) -> set[str]:
    groups: set[str] = set()
    for f in flags:
        if f.tier != "B":
            continue
        grp = f.group or SUPPORTING_GROUPS.get(f.code, "")
        if grp:
            groups.add(grp)
    return groups


def _decisive_evidence(result: PipelineResult) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in result.known_fake_flags + result.hard_flags:
        line = f.format()
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def compute_verdict(
    result: PipelineResult,
) -> tuple[str, str, int, list[str]]:
    """
    External verdict: only ОРИГИНАЛ (ЧИСТО) or ФЕЙК.
    Internal groups used only for computation and explanation.
    """
    if not result.analysis_complete:
        ev = ["[ANALYSIS_NOT_COMPLETED] полный pipeline не завершён"]
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, ev

    if result.not_a_tbank_receipt:
        ev = ["[NOT_TBANK_RECEIPT] файл не является квитанцией Т-Банка"]
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, ev

    decisive = _decisive_evidence(result)
    if decisive:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, decisive

    groups = _distinct_supporting_groups(result.supporting_flags)
    if len(groups) >= 2:
        ev = [f.format() for f in result.supporting_flags if f.tier == "B"]
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, ev

    if result.cross_document_identity_conflict:
        ev = [
            f.format()
            for f in result.hard_flags
            if f.code == "OPERATION_ID_REUSED"
        ] or ["[OPERATION_ID_REUSED] конфликт идентификатора между документами"]
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, ev

    return "ЧИСТО", "✅", 0, []


def ingest_flag(result: PipelineResult, flag: V6Flag) -> None:
    # Demoted novelty / corpus-incomplete codes never decide FAKE, even if an
    # emitter still tags them tier A.
    if flag.code in IGNORED_CODES or flag.tier == "IGNORE":
        result.ignored_observations.append(flag.format())
        return
    if flag.code in KNOWN_FAKE_CODES or flag.tier == "KNOWN":
        result.known_fake_flags.append(flag)
        return
    if flag.code in HARD_CODES or flag.tier == "A":
        if any(f.code == flag.code for f in result.hard_flags):
            return
        result.hard_flags.append(flag)
        return
    if flag.tier == "B":
        result.supporting_flags.append(flag)
        return
    result.ignored_observations.append(flag.format())
