"""SberBank v2.0 analyzer entry point (production, no shadow)."""

from __future__ import annotations

import hashlib

from .explain import build_expert_report
from .stages import run_pipeline
from .verdict import compute_verdict

VALIDATOR_VERSION = "2.1.1"


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    pipeline = run_pipeline(pdf_bytes, file_hash)
    verdict, emoji, score, forgery_flags = compute_verdict(pipeline)
    expert = build_expert_report(pipeline, verdict)

    details = {
        "file_hash": file_hash,
        "validator_version": VALIDATOR_VERSION,
        "engine": "sber_v2",
        "rollout_mode": "full",
        "bank_key": "sber",
        "profile_id": pipeline.profile_id,
        "submethod": pipeline.submethod,
        "submethod_label": pipeline.stats.get("submethod_label", ""),
        "generator_path": pipeline.generator_path,
        "new_coherent_profile": pipeline.new_coherent_profile,
        "completed_checks": pipeline.completed_checks,
        "stats": {
            k: v for k, v in pipeline.stats.items()
            if not str(k).startswith("_")
        },
        "hard_count": len(pipeline.hard_flags),
        "known_fake_count": len(pipeline.known_fake_flags),
        "supporting_count": len(pipeline.supporting_flags),
        "ignored_observations": pipeline.ignored_observations,
        "analysis_complete": pipeline.analysis_complete,
        "cross_document_identity_conflict": pipeline.cross_document_identity_conflict,
        "expert_report": expert,
        "user_message": (
            "Неизвестный банк"
            if (forgery_flags and any("NOT_SBER_RECEIPT" in f for f in forgery_flags))
            else "Обнаружена подделка." if verdict == "ФЕЙК"
            else "Неизвестный целостный профиль документа."
            if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
            else "Признаков подделки не найдено."
        ),
    }

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": score,
        "flags": forgery_flags,
        "details": details,
    }
