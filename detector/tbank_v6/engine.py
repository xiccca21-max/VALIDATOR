"""v6.0 T-Bank analyzer entry point."""

from __future__ import annotations

import hashlib

from .explain import build_expert_report
from .stages import run_pipeline
from .verdict import compute_verdict

VALIDATOR_VERSION = "6.5.7"


def analyze(pdf_bytes: bytes, file_hash: str = "", *, privileged_user: bool = False) -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    pipeline = run_pipeline(pdf_bytes, file_hash)
    verdict, emoji, score, forgery_flags = compute_verdict(pipeline)
    expert = build_expert_report(pipeline, verdict)

    details = {
        "file_hash": file_hash,
        "validator_version": VALIDATOR_VERSION,
        "engine": "tbank_v6",
        "channel": pipeline.channel,
        "receipt_subtype": pipeline.receipt_subtype,
        "receipt_subtype_label": pipeline.stats.get("receipt_subtype_label", ""),
        "completed_checks": pipeline.completed_checks,
        "stats": pipeline.stats,
        "hard_count": len(pipeline.hard_flags),
        "known_fake_count": len(pipeline.known_fake_flags),
        "supporting_count": len(pipeline.supporting_flags),
        "ignored_observations": pipeline.ignored_observations,
        "analysis_complete": pipeline.analysis_complete,
        "expert_report": expert,
        "user_message": (
            "Обнаружена подделка." if verdict == "ФЕЙК"
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
