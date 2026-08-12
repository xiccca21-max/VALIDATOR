"""VTB v2 rollout: test → percent → full (VTB_V2_ROLLOUT).

Shadow may only hide ЧИСТО / diagnostic / weak supporting.
HARD and KNOWN always surface to the user.
"""

from __future__ import annotations

import hashlib
import logging
import os

from ..hardening_v2.verdict_merge import has_decisive_evidence

log = logging.getLogger(__name__)

# Default production: full v2. Override with VTB_V2_ROLLOUT=shadow for canary.
_DEFAULT_MODE = "100"


def rollout_mode() -> str:
    # Prefer VTB_V2_ROLLOUT; fall back to VTB_V1_ROLLOUT for ops that still
    # set the old env name.
    return (
        os.environ.get("VTB_V2_ROLLOUT")
        or os.environ.get("VTB_V1_ROLLOUT")
        or _DEFAULT_MODE
    ).strip().lower()


def _in_bucket(file_hash: str, percent: int) -> bool:
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    return int(hashlib.sha256(file_hash.encode()).hexdigest(), 16) % 100 < percent


def apply_rollout(v2_result: dict, pdf_bytes: bytes, file_hash: str) -> dict:
    mode = rollout_mode()
    details = dict(v2_result.get("details") or {})
    details["rollout_mode"] = mode
    details["engine_verdict_before_rollout"] = (
        details.get("engine_verdict_before_rollout") or v2_result.get("verdict")
    )
    details["vtb_v2_shadow"] = {
        "mode": mode,
        "v2_verdict": v2_result.get("verdict"),
        "v2_score": v2_result.get("score"),
        "v2_flags": (v2_result.get("flags") or [])[:8],
        "v2_expert_report": details.get("expert_report"),
        "hard_count": details.get("hard_count"),
        "known_fake_count": details.get("known_fake_count"),
    }

    # Never hide decisive FAKE behind legacy/shadow.
    if v2_result.get("verdict") == "ФЕЙК" and has_decisive_evidence(v2_result):
        details["engine"] = "vtb_v2"
        details["verdict_after_rollout"] = "ФЕЙК"
        details["rollout_mode"] = f"{mode}+decisive_bypass"
        v2_result["details"] = details
        v2_result["score"] = max(int(v2_result.get("score") or 0), 95)
        v2_result["emoji"] = "🔴"
        return v2_result

    use_v2 = mode in {"test", "full", "100", "on", "true", "yes"}
    if mode.isdigit():
        use_v2 = _in_bucket(file_hash, int(mode))

    if use_v2:
        details["engine"] = "vtb_v2"
        details["verdict_after_rollout"] = v2_result.get("verdict")
        v2_result["details"] = details
        return v2_result

    # shadow / off → user-facing v1 ONLY when v2 is not decisive FAKE
    from ..vtb_v1.engine import analyze as analyze_v1

    v1 = analyze_v1(pdf_bytes, file_hash)
    v1_details = dict(v1.get("details") or {})
    v1_details["vtb_v2_shadow"] = details["vtb_v2_shadow"]
    v1_details["vtb_v2_shadow"]["legacy_verdict"] = v1.get("verdict")
    v1_details["vtb_v2_shadow"]["match"] = v1.get("verdict") == v2_result.get("verdict")
    v1_details["engine_verdict_before_rollout"] = details["engine_verdict_before_rollout"]
    v1_details["verdict_after_rollout"] = v1.get("verdict")
    v1_details["legacy_verdict"] = v1.get("verdict")

    # If v1 itself is decisive FAKE, keep it.
    if v1.get("verdict") == "ФЕЙК" and has_decisive_evidence(v1):
        v1["score"] = max(int(v1.get("score") or 0), 95)
        v1["emoji"] = "🔴"
        v1["details"] = v1_details
        return v1

    # Safety: never allow shadow ЧИСТО when v2 found decisive FAKE
    # (already handled above, but keep assertion trail).
    if (
        details["vtb_v2_shadow"].get("v2_verdict") == "ФЕЙК"
        and (
            int(details.get("hard_count") or 0) > 0
            or int(details.get("known_fake_count") or 0) > 0
        )
        and v1.get("verdict") == "ЧИСТО"
    ):
        log.error(
            "vtb shadow would hide FAKE hash=%s — forcing v2",
            file_hash[:12],
        )
        details["engine"] = "vtb_v2"
        details["verdict_after_rollout"] = "ФЕЙК"
        details["shadow_hide_prevented"] = True
        v2_result["details"] = details
        v2_result["verdict"] = "ФЕЙК"
        v2_result["emoji"] = "🔴"
        v2_result["score"] = max(int(v2_result.get("score") or 0), 95)
        return v2_result

    if not v1_details["vtb_v2_shadow"]["match"]:
        log.info(
            "vtb_v2 shadow mismatch hash=%s v2=%s v1=%s",
            file_hash[:12], v2_result.get("verdict"), v1.get("verdict"),
        )
    v1["details"] = v1_details
    return v1
