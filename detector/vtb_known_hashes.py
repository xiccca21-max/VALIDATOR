"""VTB known-fake file SHA hard-block — content-only, filename-agnostic."""

from __future__ import annotations

import hashlib

VTB_KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    "9ddc4942d9248cc6037734a2aadb0ff1d12419581189759ef291f5cc9da57286",
    "0f6562768c2c26d2bb3c568819cd7fdbe2e22083c3ff677d15f84b2cd3bf4db9",
})

VTB_KNOWN_FAKE_SBP_IDS: frozenset[str] = frozenset({
    "B61711110212917W0G10160011770901",
})


def check_vtb_known_file_hash(pdf_bytes: bytes) -> dict | None:
    """Exact SHA-256 match → decisive ФЕЙК before rollout/legacy/normalize."""
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if file_hash not in VTB_KNOWN_FAKE_FILE_SHA256:
        return None
    return {
        "verdict": "ФЕЙК",
        "emoji": "🔴",
        "score": 100,
        "flags": [
            f"[VTB_KNOWN_FILE_SIGNATURE] known fake SHA-256={file_hash}",
        ],
        "details": {
            "engine": "vtb_known_signatures",
            "analysis_complete": True,
            "hard_count": 0,
            "known_fake_count": 1,
            "supporting_count": 0,
            "file_hash": file_hash,
            "rollout_mode": "bypass",
            "user_message": "Обнаружена подделка.",
            "selected_engine": "vtb_known_signatures",
            "engine_verdict_before_rollout": "ФЕЙК",
            "verdict_after_rollout": "ФЕЙК",
            "first_decisive_flag": "VTB_KNOWN_FILE_SIGNATURE",
        },
        "summary": "Обнаружена подделка.",
    }
