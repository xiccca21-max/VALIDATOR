"""Structured expert explanation for Alfa v2 decisions."""

from __future__ import annotations

from .types import AlfaFlag, PipelineResult
from .verdict import distinct_supporting_groups

VARIABILITY_POLICY = (
    "Профильные отличия считаются допустимой вариативностью и не являются "
    "доказательством подделки по отдельности. ФЕЙК по Tier-B возможен только "
    "при согласии минимум двух независимых групп."
)

_IMPACT = {
    "KNOWN": "точная known-fake signature → ФЕЙК",
    "HARD": "доказанное внутреннее противоречие → ФЕЙК",
    "A": "доказанное внутреннее противоречие → ФЕЙК",
    "B": "поддерживающее наблюдение; отдельно verdict не меняет",
    "MANUAL": "совокупный неподтверждённый профиль → НЕИЗВЕСТНЫЙ ДОКУМЕНТ (не CLEAN)",
}


def _flag_lines(flag: AlfaFlag, index: int) -> list[str]:
    rule = flag.rule_id or flag.code
    lines = [f"{index}. [{rule}] {flag.detail}"]
    if flag.group:
        lines.append(f"   Group: {flag.group}")
    impact = _IMPACT.get(flag.tier.upper())
    if impact:
        lines.append(f"   Влияние: {impact}")
    return lines


def _identity_flag(pipeline: PipelineResult) -> list[AlfaFlag]:
    if not pipeline.cross_document_identity_conflict:
        return []
    if any(
        flag.code == "ALFA_OPERATION_IDENTITY_CONFLICT"
        for flag in pipeline.hard_flags
    ):
        return []
    return [AlfaFlag(
        code="ALFA_OPERATION_IDENTITY_CONFLICT",
        detail="идентификатор операции конфликтует с реквизитами другого документа",
        tier="HARD",
    )]


def _font_reassembly_lines(pipeline: PipelineResult) -> list[str]:
    stats = (pipeline.stats or {}).get("embedded_font_reassembly") or {}
    fps = stats.get("font_fingerprints") or stats.get("fonts") or []
    if isinstance(fps, dict):
        fps = list(fps.values())
    if not fps and not stats:
        return []
    lines = ["", "Embedded font reassembly forensics:"]
    for fp in fps:
        if not isinstance(fp, dict):
            continue
        role = fp.get("role") or "?"
        lines.append(
            f"• {role}: head.created={fp.get('created')} "
            f"head.modified={fp.get('modified')} "
            f"numGlyphs={fp.get('numGlyphs')} "
            f"struct_fp={fp.get('struct_fp')} "
            f"glyf={fp.get('glyf_sha12')} loca={fp.get('loca_sha12')}"
        )
        if fp.get("cogeneration_fp"):
            lines.append(f"  cogeneration_fp={fp.get('cogeneration_fp')}")
    if stats.get("f3_static") is not None:
        lines.append(
            f"• F3 static={stats.get('f3_static')} "
            f"F1 frozen_head={stats.get('f1_frozen_head')} "
            f"F2 frozen_head={stats.get('f2_frozen_head')}"
        )
    return lines


def build_expert_report(pipeline: PipelineResult, verdict: str) -> dict:
    """Build separate decisive, supporting, and ignored report sections."""

    decisive = (
        list(pipeline.known_fake_flags)
        + list(pipeline.hard_flags)
        + _identity_flag(pipeline)
    )
    supporting = list(pipeline.supporting_flags)
    ignored = list(pipeline.ignored_observations)
    groups = sorted(distinct_supporting_groups(supporting))

    decisive_text = [flag.format() for flag in decisive]
    supporting_text = [flag.format() for flag in supporting]
    body: list[str] = [
        "❌ ФЕЙК" if verdict == "ФЕЙК"
        else "⚪ НЕИЗВЕСТНЫЙ ДОКУМЕНТ" if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
        else "✅ ЧИСТО",
        "",
        f"Политика вариативности: {VARIABILITY_POLICY}",
    ]

    if not pipeline.analysis_complete:
        body.extend([
            "",
            "Решающие основания:",
            "• [ANALYSIS_NOT_COMPLETED] полный Alfa v2 pipeline не завершён.",
        ])
    elif pipeline.not_alfa_receipt:
        body.extend([
            "",
            "Решающие основания:",
            "• [NOT_ALFA_RECEIPT] файл не распознан как квитанция Альфа-Банка.",
        ])
    elif decisive:
        body.extend(["", "Решающие основания (HARD / KNOWN):"])
        for index, flag in enumerate(decisive, 1):
            body.extend(_flag_lines(flag, index))
    else:
        body.extend(["", "Решающие основания (HARD / KNOWN): отсутствуют."])

    if pipeline.manual_review_flags:
        body.extend(["", "Ручная проверка (не CLEAN):"])
        for index, flag in enumerate(pipeline.manual_review_flags, 1):
            body.extend(_flag_lines(flag, index))

    fonts_stats = (pipeline.stats.get("fonts") or {}) if isinstance(pipeline.stats, dict) else {}
    if fonts_stats.get("decisive_flag") == "ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION" or (
        fonts_stats.get("unexpected_cids")
    ):
        body.extend(["", "Oracle font subset closure:"])
        body.append(f"• used_cids: {fonts_stats.get('used_cids')}")
        body.append(f"• cmap_cids: {fonts_stats.get('cmap_cids')}")
        body.append(f"• unexpected_cids: {fonts_stats.get('unexpected_cids')}")
        body.append(f"• unexpected_unicode: {fonts_stats.get('unexpected_unicode')}")
        body.append(
            f"• decisive_flag: {fonts_stats.get('decisive_flag') or '—'}"
        )
        body.append(f"• final_verdict: {verdict}")

    body.extend(_font_reassembly_lines(pipeline))

    body.extend(["", "Поддерживающие наблюдения (Tier-B):"])
    if supporting:
        body.append(
            f"Независимые группы: {len(groups)}"
            + (f" ({', '.join(groups)})" if groups else "")
            + "."
        )
        for index, flag in enumerate(supporting, 1):
            body.extend(_flag_lines(flag, index))
        if len(groups) == 1:
            body.append("Одна Tier-B группа: verdict остаётся ЧИСТО.")
        elif len(groups) >= 2:
            body.append("Две или более независимые Tier-B группы: verdict ФЕЙК.")
    else:
        body.append("• отсутствуют")

    body.extend(["", "Игнорируемые наблюдения (IGNORE):"])
    body.extend(f"• {observation}" for observation in ignored[:20])
    if not ignored:
        body.append("• отсутствуют")

    return {
        "summary": (
            "ФЕЙК (анализ не завершён)"
            if not pipeline.analysis_complete
            else verdict
        ),
        "body_lines": body,
        "decisive": decisive_text,
        "supporting": supporting_text,
        "supporting_groups": groups,
        "ignored": ignored,
        "variability_policy": VARIABILITY_POLICY,
        "decisive_count": len(decisive),
        "supporting_count": len(supporting),
        "ignored_count": len(ignored),
    }
