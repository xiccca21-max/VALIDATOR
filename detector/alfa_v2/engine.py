"""Alfa Bank PDF validator v2 entry point."""

from __future__ import annotations

import hashlib

from .explain import build_expert_report
from .stages import run_pipeline
from .verdict import compute_verdict, distinct_supporting_groups

VALIDATOR_VERSION = "2.1.2"


def analyze(
    pdf_bytes: bytes,
    file_hash: str = "",
    *,
    privileged_user: bool = False,
) -> dict:
    """Analyze one PDF and return the common detector response shape."""

    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    pipeline = run_pipeline(pdf_bytes, file_hash)
    verdict, emoji, score, forgery_flags = compute_verdict(pipeline)
    expert = build_expert_report(pipeline, verdict)
    supporting_groups = sorted(
        distinct_supporting_groups(pipeline.supporting_flags)
    )

    details = {
        "file_hash": file_hash,
        "validator_version": VALIDATOR_VERSION,
        "version": VALIDATOR_VERSION,
        "engine": "alfa_v2",
        "rollout_mode": "full",
        "channel": pipeline.channel,
        "receipt_subtype": pipeline.receipt_subtype,
        "receipt_subtype_label": pipeline.stats.get("receipt_subtype_label", ""),
        "generator_path": pipeline.generator_path,
        "completed_checks": pipeline.completed_checks,
        "stats": pipeline.stats,
        "hard_flags": [flag.format() for flag in pipeline.hard_flags],
        "known_fake_flags": [flag.format() for flag in pipeline.known_fake_flags],
        "hard_count": len(pipeline.hard_flags),
        "known_fake_count": len(pipeline.known_fake_flags),
        "supporting_count": len(pipeline.supporting_flags),
        "supporting_groups": supporting_groups,
        "supporting_group_count": len(supporting_groups),
        "ignored_observations": pipeline.ignored_observations,
        "analysis_complete": pipeline.analysis_complete,
        "cross_document_identity_conflict": (
            pipeline.cross_document_identity_conflict
        ),
        "expert_report": expert,
        "final_verdict": verdict,
        "user_message": (
            "Обнаружена подделка."
            if verdict == "ФЕЙК"
            else "Неподтверждённый профиль — требуется ручная проверка."
            if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
            else "Признаков подделки не найдено."
        ),
        "manual_review_required": pipeline.manual_review_required,
        "manual_review_flags": [
            flag.format() for flag in pipeline.manual_review_flags
        ],
    }
    if privileged_user:
        details["evidence_policy"] = expert["variability_policy"]

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": score,
        "flags": forgery_flags,
        "details": details,
    }
