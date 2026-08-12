"""GPB v1 rollout — full only, no shadow (HARD/KNOWN always user-facing)."""

from __future__ import annotations

import os

_DEFAULT_MODE = "full"


def rollout_mode() -> str:
    return (os.environ.get("GPB_V1_ROLLOUT") or _DEFAULT_MODE).strip().lower()


def apply_rollout(v1_result: dict, pdf_bytes: bytes, file_hash: str) -> dict:
    """Always return v1 result. Shadow/legacy path removed."""
    details = dict(v1_result.get("details") or {})
    details["rollout_mode"] = "full"
    details["gpb_v1_shadow"] = None
    # Ensure decisive FAKE keeps score ≥ 95
    if v1_result.get("verdict") == "ФЕЙК":
        hard = int(details.get("hard_count") or 0)
        known = int(details.get("known_fake_count") or 0)
        if hard or known:
            v1_result["score"] = max(int(v1_result.get("score") or 0), 95)
            v1_result["emoji"] = "🔴"
    v1_result["details"] = details
    return v1_result
