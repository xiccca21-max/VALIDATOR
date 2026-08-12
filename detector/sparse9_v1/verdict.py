"""MB-* binary verdict — diagnostics never sum to FAKE."""

from __future__ import annotations

from .types import MbFlag, PipelineResult

FAKE_THRESHOLD = 60


def compute_verdict(result: PipelineResult) -> tuple[str, str, int, list[str]]:
    if not result.analysis_complete:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[ANALYSIS_NOT_COMPLETED] полный sparse9 pipeline не завершён",
        ]

    if result.not_bank_receipt:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            f"[NOT_BANK_RECEIPT] файл не является квитанцией {result.bank_key}",
        ]

    seen: set[str] = set()
    decisive: list[str] = []
    for f in result.known_fake_flags + result.hard_flags:
        line = f.format()
        if line not in seen:
            seen.add(line)
            decisive.append(line)

    if decisive:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, decisive

    if result.cross_document_identity_conflict:
        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [
            "[OPERATION_ID_REUSED] тот же ID с конфликтующими реквизитами",
        ]

    return "ЧИСТО", "✅", 0, []


def ingest_flag(result: PipelineResult, flag: MbFlag) -> None:
    if flag.tier == "KNOWN":
        result.known_fake_flags.append(flag)
    elif flag.tier == "HARD":
        result.hard_flags.append(flag)
    else:
        result.diagnostics.append(flag)
