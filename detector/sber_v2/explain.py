"""Structured expert explanation for Sber v2."""

from __future__ import annotations

from .types import PipelineResult, SberFlag
from .verdict import distinct_supporting_groups

VARIABILITY_POLICY = (
    "Новизна (hash, producer, subset, ФИО, сумма, шаблон) сама по себе не "
    "является подделкой. ФЕЙК — только HARD, KNOWN или ≥2 независимые Tier-B группы."
)

_IMPACT_BY_TIER = {
    "KNOWN": "exact known-fake signature → ФЕЙК сразу",
    "HARD": "жёсткая внутренняя несогласованность → ФЕЙК сразу",
    "SUPPORTING": "supporting (нужно ≥2 независимых группы для ФЕЙК)",
    "DIAGNOSTIC": "diagnostic — на вердикт не влияет",
}

_WHY_NOT_VARIABILITY: dict[str, str] = {
    "SBER_FONT_GLYF_UNIQ_LENS": (
        "уникальные длины nonempty glyf у sbp_outgoing Jasper лежат в узком "
        "корпусном диапазоне; выход = пересобранный glyf payload, не смена ФИО. "
        "Обход с целым визуалом: сохранить donor FontFile2 glyf vocabulary "
        "без stub-паддинга и без чужого subsetter"
    ),
    "SBER_FONT_GLYF_LOCA_CONTOUR_MISMATCH": (
        "на оригиналах sbp_outgoing loca_nonempty ≡ contour_nonempty всегда; "
        "разрыв = ghost glyf slots без контуров (SEQ pad). "
        "Обход с целым визуалом: нельзя оставлять zero-contour stubs в loca — "
        "каждый nonempty loca slot должен иметь контур"
    ),
    "SBER_FONT_HMTX_UNIQ_ADVANCES": (
        "словарь positive hmtx advances у sbp_outgoing Jasper фиксирован "
        "(425); другой размер = чужой hmtx/subsetter, не вариативность суммы. "
        "Обход с целым визуалом: не пересобирать hmtx — брать банковский "
        "advance vocabulary целиком"
    ),
    "SBER_GLYPH_PAIRS_TOO_FEW": (
        "число glyph_pairs content↔font ниже корпусного пола sbp_outgoing — "
        "недособранный subset, не короткий текст. "
        "Обход с целым визуалом: сохранить полный painted glyph pair set"
    ),
    "SBER_CONTENT_QQ_PROFILE": (
        "стек q/Q вне конечного набора sbp_outgoing — чужой clipping/graphics "
        "path в content-stream, не «новый шаблон банка». "
        "Обход с целым визуалом: копировать нативный q/Q nesting donor-чека"
    ),
    "SBER_CONTENT_TM_DECIMAL_OVERFLOW": (
        "iText 2.1.7 / Jasper пишет identity Tm только с 0 или 2 знаками "
        "после точки; ≥3 знака (65.390) — чужой float-serializer, не новая "
        "ширина ФИО. Обход с целым визуалом: эмитить Tm как iText (макс. 2 знака)"
    ),
    "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED": (
        "шаблонный ряд Jasper *.74 (615.74 / 711.74) обрезан до *.7 — это "
        "печать float, не сдвиг вёрстки. "
        "Обход с целым визуалом: писать канонический 2-знаковый token донора"
    ),
    "SBER_KNOWN_FAKE_FONTFILE2": (
        "это не «новый банковский subset»: sha16 FontFile2 уже зафиксирован "
        "на подтверждённых генераторных SEQ-фейках. У живых оригиналов Сбера "
        "тот же байтовый FontFile2 не встречается — совпадение = reuse чужого "
        "font program, а не штатная вариативность атласа"
    ),
    "SBER_FILE_SIZE_STRONG_OUTLIER": (
        "вес PDF сильно вне эталона профиля (например SBP-оригиналы ~102–103KB, "
        "генераторные шаблоны ~114KB). Небольшая вариация имён/сумм не даёт "
        "такой Δ; сильный сдвиг веса = другой container/serializer"
    ),
    "SBER_FONTFILE2_SIZE_STRONG_OUTLIER": (
        "FontFile2 вне эталона профиля (internal Jasper decoded "
        "~55136–56064 B / compressed ~24695–25383 B; SBP ~51944–53912 B). "
        "SEQ раздувает glyf или пережимает stream — rebuild font pack, "
        "не штатный банковский subset"
    ),
    "SBER_FILE_SIZE_OUTLIER": (
        "вес PDF вне мягкого диапазона профиля — supporting, не solo-HARD"
    ),
    "SBER_FONT_REVERSE_GLYPH_CLOSURE": (
        "в FontFile2 есть nonempty glyph вне замыкания used CID+composites "
        "(orphan). Банковский subset держит только нужные глифы; orphan — "
        "след reconstructed/editable font pack, а не нового шаблона"
    ),
    "SBER_INTERNAL_GLYF_NONEMPTY_FLOOR": (
        "у sber_internal_jasper (300×699) contour-nonempty glyphs всегда ≥75 "
        "(n=10). Падение при том же used-CID — under-subset FontFile2, "
        "не короче ФИО. Обход с целым визуалом: сохранить банковский subset pack"
    ),
    "SBER_INTERNAL_GLYF_COMPOSITE_FLOOR": (
        "у sber_internal_jasper composites в glyf всегда ≥14 (n=10). "
        "13 и ниже — потеря composite при reassembly. "
        "Обход с целым визуалом: не выкидывать composite glyphs из FontFile2"
    ),
    "SBER_KNOWN_FAKE_SIGNATURE": (
        "точный known-fake отпечаток документа/шрифта из malicious atlas"
    ),
    "SBER_CONTENT_SKELETON_DRIFT": (
        "порядок PDF-операторов текстового слоя (skeleton) вне atlas профиля; "
        "при near-miss это не авто-ФЕЙК, но вместе с HARD/KNOWN усиливает кейс"
    ),
    "SBER_SBP_EMPIRICAL_PROFILE": (
        "хвост/префикс СБП-ID вне наблюдавшегося empirical atlas — само по себе "
        "не HARD; ФЕЙК только с второй независимой группой или KNOWN/HARD"
    ),
    "SBER_FONT_LAYER_CONTAMINATION": (
        "форензика шрифтового слоя дала HIGH-вес на Jasper/pdfium профиле — "
        "не нормальная смена subset, а чужой font builder / cross-layer mismatch"
    ),
    "SBER_NEW_FONTFILE2_SHA": (
        "новый FontFile2 sha16 вне atlas — diagnostic only: новизна ≠ подделка"
    ),
}

_OBJECT_HINT: dict[str, str] = {
    "SBER_KNOWN_FAKE_FONTFILE2": "Font: FontFile2 (embedded TTF bytes)",
    "SBER_FILE_SIZE_STRONG_OUTLIER": "Container: PDF byte size vs profile",
    "SBER_FONTFILE2_SIZE_STRONG_OUTLIER": "Font: FontFile2 decoded byte size vs profile",
    "SBER_FILE_SIZE_OUTLIER": "Container: PDF byte size vs profile",
    "SBER_FONT_REVERSE_GLYPH_CLOSURE": "Font: glyf closure vs used CIDs",
    "SBER_INTERNAL_GLYF_NONEMPTY_FLOOR": "Font: internal nonempty floor",
    "SBER_INTERNAL_GLYF_COMPOSITE_FLOOR": "Font: internal composite floor",
    "SBER_KNOWN_FAKE_SIGNATURE": "Document: known-fake atlas hit",
    "SBER_CONTENT_SKELETON_DRIFT": "Content stream: operator skeleton",
    "SBER_CONTENT_TM_DECIMAL_OVERFLOW": "Content stream: Tm float spelling",
    "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED": "Content stream: template Tm.y token",
    "SBER_SBP_EMPIRICAL_PROFILE": "Field: СБП operation id tail",
    "SBER_FONT_LAYER_CONTAMINATION": "Font layer forensics",
}


def _flag_lines(flag: SberFlag, index: int) -> list[str]:
    lines = [f"{index}. [{flag.rule_id or flag.code}] {flag.detail}"]
    obj = _OBJECT_HINT.get(flag.code, "")
    if obj:
        lines.append(f"   Object: {obj}")
    if flag.group:
        lines.append(f"   Group: {flag.group}")
    why = _WHY_NOT_VARIABILITY.get(flag.code, "")
    if why:
        if "Обход с целым визуалом:" in why:
            head, _, bypass = why.partition("Обход с целым визуалом:")
            head = head.strip().rstrip(".")
            if head:
                lines.append(f"   Почему не вариативность: {head}")
            lines.append(f"   Обход с целым визуалом: {bypass.strip()}")
        else:
            lines.append(f"   Почему не вариативность: {why}")
    impact = _IMPACT_BY_TIER.get(flag.tier, "")
    if impact:
        lines.append(f"   Влияние: {impact}")
    else:
        lines.append(f"   Tier: {flag.tier}")
    return lines


def build_expert_report(pipeline: PipelineResult, verdict: str) -> dict:
    decisive = list(pipeline.known_fake_flags) + list(pipeline.hard_flags)
    supporting = list(pipeline.supporting_flags)
    groups = sorted(distinct_supporting_groups(supporting))
    body: list[str] = [
        "❌ ФЕЙК" if verdict == "ФЕЙК"
        else "⚪ НЕИЗВЕСТНЫЙ ДОКУМЕНТ" if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
        else "✅ ЧИСТО",
        "",
        f"profile_id: {pipeline.profile_id or '—'}",
        f"generator_path: {pipeline.generator_path or '—'}",
    ]

    if verdict == "ФЕЙК":
        # @kronlead: HARD/KNOWN only — no Tier-B fluff.
        body.append("")
        body.append(f"❌ ФЕЙК — обнаружено {len(decisive)} решающих HARD/KNOWN")
        body.append("")
        if decisive:
            for i, flag in enumerate(decisive, 1):
                body.extend(_flag_lines(flag, i))
                body.append("")
        else:
            body.append(
                "ФЕЙК без одиночного HARD: сработали supporting-группы "
                f"({', '.join(groups) if groups else '—'})."
            )
            body.append("")
            for i, flag in enumerate(supporting, 1):
                body.extend(_flag_lines(flag, i))
                body.append("")
    else:
        body.extend([
            "",
            "Почему прошло:",
            "• hard/known signatures не сработали",
            "• новизна subset/hash/ФИО сама по себе не банится "
            "(см. ignored / diagnostic ниже)",
        ])
        if supporting:
            body.append(
                f"• есть {len(supporting)} supporting-флагов, но "
                f"<2 независимых групп → не ФЕЙК"
            )
        body.extend(["", "Что можно улучшить по этому оригиналу:"])
        body.append(
            "• если FontFile2 sha16 новый — это кандидат в atlas genuine, "
            "не в known-fake pins"
        )
        body.append(
            "• skeleton/route/slot из ЧИСТО можно добавить в trusted profiles "
            "только после ручной проверки, что это банк, а не generator slip"
        )

    # @kronlead FAKE: HARD/KNOWN body only. Diagnostics stay for CLEAN.
    if verdict != "ФЕЙК":
        body.extend(["", "Игнорируемые / diagnostic наблюдения:"])
        body.extend(f"• {item}" for item in pipeline.ignored_observations[:12])
        if not pipeline.ignored_observations:
            body.append("• отсутствуют")

    rebuild = (pipeline.stats or {}).get("embedded_font_reassembly") or {}
    return {
        "summary": verdict,
        "body_lines": body,
        "decisive": [f.format() for f in decisive],
        "supporting": [f.format() for f in supporting],
        "supporting_groups": groups,
        "ignored": list(pipeline.ignored_observations),
        "variability_policy": VARIABILITY_POLICY,
        "decisive_count": len(decisive),
        "supporting_count": len(supporting),
        "embedded_font_reassembly": rebuild,
    }
