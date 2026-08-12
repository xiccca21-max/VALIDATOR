"""VTB v1.0 expert report for @kronlead (spec §16)."""



from __future__ import annotations



from .types import PipelineResult, VtbFlag



_FORBIDDEN = (

    "не соответствует профилю оригиналов",

    "чужие полосы",

    "render rows",

    "pixel stripes",

)





def _lines(flag: VtbFlag, idx: int) -> list[str]:

    rid = flag.rule_id or flag.code

    out = [f"{idx}. [{rid}] {flag.detail}"]

    if flag.group:

        out.append(f"   Group: {flag.group}")

    if flag.expected:

        out.append(f"   Expected: {flag.expected}")

    if flag.actual:

        out.append(f"   Actual: {flag.actual}")

    if flag.tier == "HARD":

        out.append("   Влияние: hard cross-layer inconsistency → ФЕЙК")

    return out





def build_expert_report(pipeline: PipelineResult, verdict: str) -> dict:

    body: list[str] = []

    decisive = pipeline.known_fake_flags + pipeline.hard_flags

    diag_text = [f.format() for f in pipeline.diagnostics]



    if not pipeline.analysis_complete:

        return {

            "summary": "ФЕЙК (анализ не завершён)",

            "body_lines": ["❌ ФЕЙК — анализ не завершён", "", "[ANALYSIS_NOT_COMPLETED]"],

        }



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

            "Полный VTB pipeline завершён. Hard-нарушений, known-fake signatures "

            "и конфликтов идентификаторов не обнаружено."

        )

        body.append(f"Проверены: {', '.join(pipeline.completed_checks)}.")

        if pipeline.family:

            body.append(f"Семейство: {pipeline.family}.")

        if pipeline.generator_path:

            body.append(f"Generator: {pipeline.generator_path}.")



    filtered = [d for d in diag_text if not any(p in d.lower() for p in _FORBIDDEN)]

    if filtered:

        body.append("")

        body.append("Диагностика, не влияющая на verdict:")

        for d in filtered[:14]:

            body.append(f"• {d}")



    summary = "ОРИГИНАЛ" if verdict != "ФЕЙК" else f"ФЕЙК ({len(decisive)} нарушений)"

    return {

        "summary": summary,

        "body_lines": body,

        "decisive_count": len(decisive),

        "diagnostic_count": len(filtered),

    }

