"""
Банк ВТБ — v2.0 future-safe validator (T-Bank verdict model).

Decision engine: detector/vtb_v2/
Rollout: VTB_V2_ROLLOUT=test|shadow|N|100|full  (default 100)
Also respects VTB_V1_ROLLOUT for legacy shadow path.

HARD and KNOWN always reach the user — never hidden by shadow/legacy.
"""

from __future__ import annotations

from .hardening_v2.verdict_merge import has_decisive_evidence
from .vtb_known_hashes import check_vtb_known_file_hash
from .vtb_v2.engine import VALIDATOR_VERSION, analyze as analyze_v2
from .vtb_v2.rollout import apply_rollout

__all__ = ["analyze", "VALIDATOR_VERSION", "analyze_v2"]


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    # Content-only hard-block (also done in route — belt and suspenders).
    early = check_vtb_known_file_hash(pdf_bytes)
    if early is not None:
        return early

    v2 = analyze_v2(pdf_bytes, file_hash)
    details = dict(v2.get("details") or {})
    details["engine_verdict_before_rollout"] = v2.get("verdict")
    v2["details"] = details

    # HARD / KNOWN always returned to the user, regardless of rollout.
    if v2.get("verdict") == "ФЕЙК" and has_decisive_evidence(v2):
        details["rollout_mode"] = details.get("rollout_mode") or "decisive_bypass"
        details["verdict_after_rollout"] = "ФЕЙК"
        details["engine"] = details.get("engine") or "vtb_v2"
        v2["score"] = max(int(v2.get("score") or 0), 95)
        v2["emoji"] = "🔴"
        v2["details"] = details
        return v2

    return apply_rollout(v2, pdf_bytes, file_hash)
