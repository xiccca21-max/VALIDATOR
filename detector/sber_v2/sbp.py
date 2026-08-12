"""SBP linked tuple checks for Sber v2."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..sber_profiles import extract_sbp_opid
from ..sber_sbp_cipher import validate_legacy_document, validate_sber_sbp_cipher
from ..sber_profiles import extract_legacy_document
from .atlas import known_sbp_markers, known_sbp_tail_prefixes
from .types import SberFlag

_TS_HARD_CODES = frozenset({
    "SBER_SBP_ID_TIMESTAMP",
    "SBER_SBP_ID_STRUCTURE",
    "SBER_SBP_ID_MISSING",
})


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "identifier") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_sbp_linked_tuple(
    text: str,
    *,
    profile_id: str,
) -> CheckResult:
    out = CheckResult()
    try:
        if profile_id not in ("sbp_outgoing", "sbp_request"):
            if profile_id == "legacy_phone":
                doc = extract_legacy_document(text)
                out.stats["legacy_document"] = doc
                if doc:
                    leg = validate_legacy_document(doc, text)
                    out.stats["legacy_cipher"] = leg.stats
                    for lf in leg.flags:
                        out.flags.append(_f(lf.code, lf.detail))
            return out

        opid = extract_sbp_opid(text)
        out.stats["sbp_opid"] = opid
        cipher = validate_sber_sbp_cipher(opid or "", text)
        out.stats["sbp_cipher"] = cipher.stats

        for cf in cipher.flags:
            if cf.code in _TS_HARD_CODES:
                # Map timestamp conflicts to linked-tuple HARD (+ |Δt|>15 via cipher)
                code = (
                    "SBER_SBP_LINKED_TUPLE_CONFLICT"
                    if cf.code == "SBER_SBP_ID_TIMESTAMP"
                    else cf.code
                )
                out.flags.append(_f(code, cf.detail))
                if cf.code == "SBER_SBP_ID_TIMESTAMP":
                    out.flags.append(_f("SBER_SBP_TIMESTAMP_MISMATCH", cf.detail))
                else:
                    out.flags.append(_f("SBER_SBP_LINKED_TUPLE_CONFLICT", cf.detail))
            else:
                out.flags.append(_f(cf.code, cf.detail, tier="DIAGNOSTIC"))

        # Empirical marker / tail prefix — Tier-B until corpus confirms
        if opid and len(opid) == 32:
            marker = opid[0]
            tail_p4 = opid[11:15]
            markers = known_sbp_markers()
            prefixes = known_sbp_tail_prefixes()
            if markers and marker not in markers:
                out.flags.append(_f(
                    "SBER_SBP_MARKER_UNKNOWN",
                    f"маркер «{marker}» вне atlas",
                    tier="B",
                    group="B5_sbp_empirical",
                ))
                out.flags.append(_f(
                    "SBER_SBP_EMPIRICAL_PROFILE",
                    f"unknown marker {marker}",
                    tier="B",
                    group="B5_sbp_empirical",
                ))
            if prefixes and tail_p4 not in prefixes:
                out.flags.append(_f(
                    "SBER_SBP_TAIL_UNKNOWN",
                    f"хвост prefix «{tail_p4}» вне atlas",
                    tier="B",
                    group="B5_sbp_empirical",
                ))

        # Hard |Δt| observation from cipher stats (cipher already hardens >90s;
        # plan: |Δt|>15s HARD — reinforce if drift recorded outside soft window)
        drift = cipher.stats.get("utc_diff_sec")
        if isinstance(drift, (int, float)) and abs(drift) > 15:
            # Only escalate if not already flagged hard by cipher (>90)
            if not any(f.code == "SBER_SBP_LINKED_TUPLE_CONFLICT" for f in out.flags):
                if abs(drift) > 15:
                    # Soft corpus window is 0–15; outside → HARD per plan
                    out.flags.append(_f(
                        "SBER_SBP_LINKED_TUPLE_CONFLICT",
                        f"|Δt|={abs(int(drift))}s > 15s между SBP core и операцией",
                    ))
                    out.flags.append(_f(
                        "SBER_SBP_TIMESTAMP_MISMATCH",
                        f"|Δt|={abs(int(drift))}s",
                    ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
