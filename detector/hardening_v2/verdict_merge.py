"""v2.0 priority over bank v1 — diagnostics never become ФЕЙК alone."""

from __future__ import annotations

import re

_DIAGNOSTIC_PATTERNS = (
    r"STREAM_COMPRESSION_RATIO_OUTLIER",
    r"UNEXPECTED_STREAM_FILTER",
    r"DECODED_STREAM_SIZE_OUTLIER",
    r"STREAM_FILTER_ANOMALY",
    r"OPENACTION_PRESENT",
    r"STREAM_DECOMPRESSION_FAILED",
    r"STREAM_LENGTH_MISMATCH",
    r"OBJECT_GRAPH_INCONSISTENT",
    r"FOREIGN_PRODUCER",
    r"PDF_MODDATE_EDITED",
    r"PROFILE_CLUSTER_OUTLIER",
    r"GLYPH_COUNT_OUTLIER",
    r"NEW_.*PROFILE",
    r"UNKNOWN_.*",
    r"SHADOW",
    r"diagnostic",
)

_DIAG_RE = re.compile("|".join(_DIAGNOSTIC_PATTERNS), re.I)


def _is_diagnostic_flag(flag: str) -> bool:
    return bool(_DIAG_RE.search(flag or ""))


def has_decisive_evidence(result: dict) -> bool:
    """HARD / KNOWN evidence must never be downgraded to ЧИСТО."""
    details = result.get("details") or {}
    if int(details.get("hard_count") or 0) > 0:
        return True
    if int(details.get("known_fake_count") or 0) > 0:
        return True
    if details.get("hard_flags") or details.get("known_fake_flags"):
        return True
    for flag in result.get("flags") or []:
        u = str(flag).upper()
        if "KNOWN" in u or "[VTB_KNOWN_" in u or "[ALFA_KNOWN_" in u:
            return True
        if any(
            code in u
            for code in (
                "VTB_METHOD_",
                "VTB_SBP_LINKED_TUPLE_KNOWN_FAKE",
                "VTB_SBP_TAIL_SPLICE_KNOWN_FAKE",
                "VTB_KNOWN_FAKE_SBP_ID",
                "VTB_KNOWN_FILE_SIGNATURE",
                "ANALYSIS_NOT_COMPLETED",
            )
        ):
            return True
    if str(result.get("verdict") or "") == "ФЕЙК" and (
        int(details.get("hard_count") or 0) > 0
        or int(details.get("known_fake_count") or 0) > 0
    ):
        return True
    return False


def apply_v2_priority(result: dict, *, hardening_hard: bool = False) -> dict:
    """
    If bank v1 returned ФЕЙК only from diagnostic/supporting flags — downgrade to ЧИСТО.
    Hard v2 flags already returned before bank analyze.

    Alfa/Sber/VTB engines are never downgraded: any HARD/KNOWN they emit is production-final.
    """
    if hardening_hard:
        return result

    if has_decisive_evidence(result):
        out = dict(result)
        out["verdict"] = "ФЕЙК"
        out["emoji"] = "🔴"
        out["score"] = max(int(out.get("score") or 0), 95)
        return out

    if result.get("verdict") != "ФЕЙК":
        return result

    details = result.get("details") or {}
    engine = str(details.get("engine") or "")
    if engine.startswith("alfa") or engine.startswith("sber") or engine.startswith("vtb") or engine.startswith("gpb"):
        return result
    if details.get("hard_count") or details.get("known_fake_count"):
        return result
    if details.get("cross_document_identity_conflict"):
        return result
    hard_flags = details.get("hard_flags") or []
    if hard_flags:
        return result

    flags = list(result.get("flags") or [])
    if not flags:
        return result
    # Never treat Alfa HARD codes as suppressible diagnostics.
    if any(
        ("[ALFA_" in (f or "") or str(f).startswith("ALFA_"))
        and "DIAGNOSTIC" not in (f or "").upper()
        for f in flags
    ):
        return result
    decisive = [f for f in flags if not _is_diagnostic_flag(f)]
    if decisive:
        return result
    out = dict(result)
    out["verdict"] = "ЧИСТО"
    out["emoji"] = "✅"
    out["score"] = 0
    out["flags"] = []
    details = dict(out.get("details") or {})
    details["v2_downgraded_diagnostic_fake"] = True
    details["v2_suppressed_flags"] = flags[:8]
    out["details"] = details
    return out
