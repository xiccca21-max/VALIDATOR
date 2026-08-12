"""Sber v1.0 expert report for @kronlead (spec §16)."""



from __future__ import annotations



from .types import PipelineResult, SberFlag



_FORBIDDEN = (

    "не соответствует профилю оригиналов",

    "чужие полосы",

    "render rows",

    "pixel stripes",

    "pixel-row",

    "row fingerprint",

)





def _lines(flag: SberFlag, idx: int) -> list[str]:

    rid = flag.rule_id or flag.code

    out = [f"{idx}. [{rid}] {flag.detail}"]

    if flag.group:

        out.append(f"   Group: {flag.group}")

    if flag.expected:

        out.append(f"   Expected: {flag.expected}")

    if flag.actual:

        out.append(f"   Actual: {flag.actual}")

    if flag.raw_evidence:

        out.append(f"   Raw: {flag.raw_evidence[:200]}")

    if flag.tier == "KNOWN":

        out.append("   Влияние: confirmed known-fake signature → ФЕЙК")

    elif flag.tier == "HARD":

        out.append("   Влияние: hard cross-layer inconsistency → ФЕЙК")

    return out





def build_expert_report(pipeline: PipelineResult, verdict: str) -> dict:

    body: list[str] = []

    decisive = pipeline.known_fake_flags + pipeline.hard_flags

    diag_text = [f.format() for f in pipeline.diagnostics]



    if not pipeline.analysis_complete:

        body = [

            "❌ ФЕЙК — анализ не завершён",

            "",

            "[ANALYSIS_NOT_COMPLETED] технический сбой, не доказанная пересборка.",

        ]

        return {"summary": "ФЕЙК (анализ не завершён)", "body_lines": body}



    if verdict == "ФЕЙК":

        body.append(f"❌ ФЕЙК — обнаружено {len(decisive)} доказанных нарушений")

        body.append("")

        for i, f in enumerate(decisive, 1):

            body.extend(_lines(f, i))

            body.append("")

    else:

        body.append("✅ ОРИГИНАЛ")

        body.append("")

        body.append(

            "Full Sber pipeline завершён. Concrete hard contradictions и "

            "confirmed fake signatures не обнаружены."

        )

        checks = ", ".join(pipeline.completed_checks) or (

            "raw PDF/xref/EOF, object graph, streams, active content, content AST, "

            "fonts/CMap/W/glyph, семантика подметода, IDs/time, parser/render parity"

        )

        body.append(f"Проверены: {checks}.")

        if pipeline.submethod:

            body.append(f"Подметод: {pipeline.submethod}.")

        if pipeline.new_coherent_profile:

            body.append("Метка: new_coherent_profile (будущая согласованная версия).")

        if pipeline.generator_path:

            body.append(f"Generator path: {pipeline.generator_path}.")



    filtered_diag = [

        d for d in diag_text

        if not any(p in d.lower() for p in _FORBIDDEN)

    ]

    if filtered_diag:

        body.append("")

        body.append("Диагностика, не влияющая на verdict:")

        for d in filtered_diag[:14]:

            body.append(f"• {d}")



    summary = "ОРИГИНАЛ" if verdict != "ФЕЙК" else "ФЕЙК"

    if pipeline.analysis_complete and verdict == "ФЕЙК":

        summary = f"ФЕЙК ({len(decisive)} нарушений)"

    return {

        "summary": summary,

        "body_lines": body,

        "decisive_count": len(decisive),

        "diagnostic_count": len(filtered_diag),

    }

