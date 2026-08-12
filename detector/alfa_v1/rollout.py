"""Alfa v1 rollout: shadow mode + staged feature flag (spec §17)."""

from __future__ import annotations

import hashlib
import logging
import os

log = logging.getLogger(__name__)

# full | shadow | 0 | 10 | 50 | 100 — production default is full (no legacy return)
_DEFAULT_MODE = "full"


def rollout_mode() -> str:
    return (os.environ.get("ALFA_V1_ROLLOUT") or _DEFAULT_MODE).strip().lower()


def _in_rollout_bucket(file_hash: str, percent: int) -> bool:
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    bucket = int(hashlib.sha256(file_hash.encode()).hexdigest(), 16) % 100
    return bucket < percent


def apply_rollout(v1_result: dict, pdf_bytes: bytes, file_hash: str) -> dict:
    """
    shadow: v1 verdict logged in details, legacy returned to user.
    N (10/50/100): v1 for N% traffic by file hash, legacy otherwise.
    """
    mode = rollout_mode()
    details = dict(v1_result.get("details") or {})
    details["alfa_v1_shadow"] = {
        "mode": mode,
        "v1_verdict": v1_result.get("verdict"),
        "v1_score": v1_result.get("score"),
        "v1_flags": (v1_result.get("flags") or [])[:8],
        "v1_expert_report": (v1_result.get("details") or {}).get("expert_report"),
    }

    if mode == "shadow":
        from ..alfa_legacy import analyze as analyze_legacy

        legacy = analyze_legacy(pdf_bytes, file_hash)
        details["alfa_v1_shadow"]["legacy_verdict"] = legacy.get("verdict")
        details["alfa_v1_shadow"]["match"] = (
            legacy.get("verdict") == v1_result.get("verdict")
        )
        if not details["alfa_v1_shadow"]["match"]:
            log.info(
                "alfa_v1 shadow mismatch hash=%s v1=%s legacy=%s",
                file_hash[:12],
                v1_result.get("verdict"),
                legacy.get("verdict"),
            )
        legacy_details = dict(legacy.get("details") or {})
        legacy_details["alfa_v1_shadow"] = details["alfa_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    if mode.isdigit():
        pct = int(mode)
        if _in_rollout_bucket(file_hash, pct):
            v1_result["details"] = details
            return v1_result
        from ..alfa_legacy import analyze as analyze_legacy

        legacy = analyze_legacy(pdf_bytes, file_hash)
        legacy_details = dict(legacy.get("details") or {})
        legacy_details["alfa_v1_shadow"] = details["alfa_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    # full v1 (any other value)
    v1_result["details"] = details
    return v1_result
