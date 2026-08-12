"""VTB Bank v2.0 analyzer entry point."""

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
        "engine": "vtb_v2",
        "rollout_mode": "full",
        "bank_key": "vtb",
        "subtype": pipeline.subtype,
        "submethod": pipeline.subtype,
        "submethod_label": pipeline.stats.get("subtype_label", ""),
        "generator_path": pipeline.generator_path,
        "profile_version": pipeline.profile_version,
        "new_coherent_profile": pipeline.new_coherent_profile,
        "completed_checks": pipeline.completed_checks,
        "stats": {
            k: v for k, v in pipeline.stats.items()
            if k not in {"assembly_components"}
        },
        "hard_count": len(pipeline.hard_flags),
        "known_fake_count": len(pipeline.known_fake_flags),
        "supporting_count": len(pipeline.supporting_flags),
        "hard_flags": [f.format() for f in pipeline.hard_flags],
        "known_fake_flags": [f.format() for f in pipeline.known_fake_flags],
        "ignored_observations": pipeline.ignored_observations,
        "analysis_complete": pipeline.analysis_complete,
        "cross_document_identity_conflict": pipeline.cross_document_identity_conflict,
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
