"""Sparse9 v1 analyzer entry point."""

from __future__ import annotations

import hashlib

from ..sparse9_profiles import BANK_CONTRACTS, SPEC_IDS
from .explain import build_expert_report
from .stages import run_pipeline
from .verdict import compute_verdict

VALIDATOR_VERSION = "1.0.2-future-safe"


def analyze(pdf_bytes: bytes, bank_key: str, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    pipeline = run_pipeline(pdf_bytes, file_hash, bank_key)
    verdict, emoji, score, forgery_flags = compute_verdict(pipeline)
    expert = build_expert_report(pipeline, verdict)
    contract = BANK_CONTRACTS.get(bank_key)

    details = {
        "file_hash": file_hash,
        "validator_version": VALIDATOR_VERSION,
        "engine": "sparse9_v1",
        "bank_key": bank_key,
        "bank_spec_id": SPEC_IDS.get(bank_key, ""),
        "bank_display": contract.display_name if contract else bank_key,
        "method": pipeline.method,
        "method_code": pipeline.stats.get("method_code", ""),
        "generator_path": pipeline.generator_path,
        "completed_checks": pipeline.completed_checks,
        "stats": pipeline.stats,
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
