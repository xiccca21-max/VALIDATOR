"""VTB v1 rollout: shadow mode + staged feature flag (spec §17).

HARD/KNOWN never hidden by shadow → legacy.
Default VTB_V1_ROLLOUT=100 after regression.
"""

from __future__ import annotations

import hashlib
import logging
import os

from ..hardening_v2.verdict_merge import has_decisive_evidence

log = logging.getLogger(__name__)

_DEFAULT_MODE = "100"


def rollout_mode() -> str:
    return (os.environ.get("VTB_V1_ROLLOUT") or _DEFAULT_MODE).strip().lower()


def _in_rollout_bucket(file_hash: str, percent: int) -> bool:
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    bucket = int(hashlib.sha256(file_hash.encode()).hexdigest(), 16) % 100
    return bucket < percent


def apply_rollout(v1_result: dict, pdf_bytes: bytes, file_hash: str) -> dict:
    mode = rollout_mode()
    details = dict(v1_result.get("details") or {})
    details["vtb_v1_shadow"] = {
        "mode": mode,
        "v1_verdict": v1_result.get("verdict"),
        "v1_score": v1_result.get("score"),
        "v1_flags": (v1_result.get("flags") or [])[:8],
        "v1_expert_report": (v1_result.get("details") or {}).get("expert_report"),
        "hard_count": details.get("hard_count"),
        "known_fake_count": details.get("known_fake_count"),
    }

    # HARD and KNOWN always returned to the user, regardless of rollout.
    if v1_result.get("verdict") == "ФЕЙК" and has_decisive_evidence(v1_result):
        details["verdict_after_rollout"] = "ФЕЙК"
        details["rollout_mode"] = f"{mode}+decisive_bypass"
        v1_result["details"] = details
        v1_result["score"] = max(int(v1_result.get("score") or 0), 95)
        v1_result["emoji"] = "🔴"
        return v1_result

    if mode == "shadow":
        from ..vtb_legacy import analyze as analyze_legacy

        legacy = analyze_legacy(pdf_bytes, file_hash)
        details["vtb_v1_shadow"]["legacy_verdict"] = legacy.get("verdict")
        details["vtb_v1_shadow"]["match"] = (
            legacy.get("verdict") == v1_result.get("verdict")
        )
        if not details["vtb_v1_shadow"]["match"]:
            log.info(
                "vtb_v1 shadow mismatch hash=%s v1=%s legacy=%s",
                file_hash[:12],
                v1_result.get("verdict"),
                legacy.get("verdict"),
            )
        # Never allow legacy ЧИСТО when v1 found decisive FAKE (already bypassed)
        # or when shadow would hide a FAKE.
        if (
            details["vtb_v1_shadow"].get("v1_verdict") == "ФЕЙК"
            and legacy.get("verdict") == "ЧИСТО"
        ):
            log.error(
                "vtb_v1 shadow hide prevented hash=%s", file_hash[:12],
            )
            details["shadow_hide_prevented"] = True
            details["verdict_after_rollout"] = "ФЕЙК"
            v1_result["details"] = details
            v1_result["verdict"] = "ФЕЙК"
            v1_result["emoji"] = "🔴"
            v1_result["score"] = max(int(v1_result.get("score") or 0), 95)
            return v1_result

        legacy_details = dict(legacy.get("details") or {})
        legacy_details["vtb_v1_shadow"] = details["vtb_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    if mode.isdigit():
        pct = int(mode)
        if _in_rollout_bucket(file_hash, pct):
            details["verdict_after_rollout"] = v1_result.get("verdict")
            v1_result["details"] = details
            return v1_result
        from ..vtb_legacy import analyze as analyze_legacy

        legacy = analyze_legacy(pdf_bytes, file_hash)
        legacy_details = dict(legacy.get("details") or {})
        legacy_details["vtb_v1_shadow"] = details["vtb_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    details["verdict_after_rollout"] = v1_result.get("verdict")
    v1_result["details"] = details
    return v1_result
