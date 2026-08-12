"""VTB v1.0 future-safe binary verdict (spec §3)."""



from __future__ import annotations



from .types import PipelineResult, VtbFlag



FAKE_THRESHOLD = 60





def _decisive_evidence(result: PipelineResult) -> list[str]:

    seen: set[str] = set()

    out: list[str] = []

    for f in result.known_fake_flags + result.hard_flags:

        line = f.format()

        if line not in seen:

            seen.add(line)

            out.append(line)

    return out





def compute_verdict(result: PipelineResult) -> tuple[str, str, int, list[str]]:

    if not result.analysis_complete:

        return "ФЕЙК", "🔴", FAKE_THRESHOLD, [

            "[ANALYSIS_NOT_COMPLETED] полный VTB pipeline не завершён",

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

            "[OPERATION_ID_REUSED] тот же SBP ID с конфликтующими реквизитами",

        ]



    return "ЧИСТО", "✅", 0, []





def ingest_flag(result: PipelineResult, flag: VtbFlag) -> None:

    if flag.tier == "KNOWN" or flag.code in {"VTB-KNOWN-001"}:

        result.known_fake_flags.append(flag)

    elif flag.tier == "HARD":

        result.hard_flags.append(flag)

    else:

        result.diagnostics.append(flag)

