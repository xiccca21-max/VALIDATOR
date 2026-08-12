"""Structured expert explanation for VTB v2."""

from __future__ import annotations

from .types import PipelineResult, VtbFlag
from .verdict import distinct_supporting_groups

VARIABILITY_POLICY = (
    "Новизна (FontFile2 SHA, subset, /ID, размер, CID count, получатель, сумма, "
    "SBP tuple, content length от ФИО, Producer openhtmltopdf) сама по себе "
    "не является подделкой. ФЕЙК — только HARD, KNOWN_FAKE или ≥2 независимые "
    "Tier-B группы. HARD по /W: слишком мало CID-run в Widths (пересборка)."
)


def _flag_lines(flag: VtbFlag, index: int) -> list[str]:
    lines = [f"{index}. [{flag.rule_id or flag.code}] {flag.detail}"]
    if flag.group:
        lines.append(f"   Group: {flag.group}")
    lines.append(f"   Tier: {flag.tier}")
    return lines


def build_expert_report(pipeline: PipelineResult, verdict: str) -> dict:
    decisive = list(pipeline.known_fake_flags) + list(pipeline.hard_flags)
    supporting = list(pipeline.supporting_flags)
    groups = sorted(distinct_supporting_groups(supporting))
    body: list[str] = [
        "❌ ФЕЙК" if verdict == "ФЕЙК" else "✅ ЧИСТО",
        "",
        f"Политика: {VARIABILITY_POLICY}",
        f"subtype: {pipeline.subtype or '—'}",
        f"profile_version: {pipeline.profile_version}",
        f"generator_path: {pipeline.generator_path or '—'}",
    ]
    body.extend(["", "Решающие основания (HARD / KNOWN):"])
    if decisive:
        for i, flag in enumerate(decisive, 1):
            body.extend(_flag_lines(flag, i))
    else:
        body.append("• отсутствуют")
    body.extend(["", "Поддерживающие наблюдения (Tier-B):"])
    if supporting:
        body.append(
            f"Независимые группы: {len(groups)}"
            + (f" ({', '.join(groups)})" if groups else "")
        )
        for i, flag in enumerate(supporting, 1):
            body.extend(_flag_lines(flag, i))
    else:
        body.append("• отсутствуют")
    body.extend(["", "Игнорируемые наблюдения:"])
    if pipeline.ignored_observations:
        body.extend(f"• {item}" for item in pipeline.ignored_observations[:20])
    else:
        body.append("• отсутствуют")
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
    }
