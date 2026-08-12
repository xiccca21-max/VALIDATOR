"""Content operator grammar / skeleton checks for Sber v2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..structure import content_skeleton_hash, content_stream_bytes
from .profile_gates import profile_skeleton_known
from .types import SberFlag

# sbp_outgoing Jasper/iText genuines (n=41): only these q/Q pairs appear.
# SEQ near-miss shells keep BT/ET=25 but drift clipping stack (7/6, 9/4, 9/6…).
_SBP_OUTGOING_QQ_ALLOWED: frozenset[tuple[int, int]] = frozenset({
    (7, 4),
    (8, 4),
    (8, 5),
})

# sber_internal_jasper genuines (n=15): only these q/Q pairs appear.
# SEQ internals often emit 12/4, 11/5, 12/5 (absent from corpus).
_SBER_INTERNAL_QQ_ALLOWED: frozenset[tuple[int, int]] = frozenset({
    (10, 4),
    (11, 4),
    (13, 4),
})

_QQ_ALLOWED_BY_PROFILE: dict[str, frozenset[tuple[int, int]]] = {
    "sbp_outgoing": _SBP_OUTGOING_QQ_ALLOWED,
    "sber_internal_jasper": _SBER_INTERNAL_QQ_ALLOWED,
}


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_content_grammar(
    pdf_bytes: bytes,
    *,
    profile_id: str = "",
) -> CheckResult:
    out = CheckResult()
    try:
        content = content_stream_bytes(pdf_bytes)
        out.stats["content_len"] = len(content or b"")
        if not content:
            return out

        bt = len(re.findall(rb"\bBT\b", content))
        et = len(re.findall(rb"\bET\b", content))
        q_ops = len(re.findall(rb"\bq\b", content))
        Q_ops = len(re.findall(rb"\bQ\b", content))
        out.stats["bt_et"] = {"bt": bt, "et": et, "q": q_ops, "Q": Q_ops}

        if bt != et:
            out.flags.append(_f(
                "SBER_CONTENT_OPERATOR_GRAMMAR_CONFLICT",
                f"несбалансированные BT/ET: {bt} vs {et}",
                group="visibility",
            ))
            out.flags.append(_f(
                "SBER_BT_ET_MISMATCH",
                f"BT={bt} ET={et}",
                group="visibility",
            ))
        elif q_ops != Q_ops:
            # Jasper/Quartz clipping routinely imbalances q/Q — diagnostic only.
            out.flags.append(_f(
                "SBER_VIS_OPERATOR_DRIFT",
                f"q/Q count drift ({q_ops}/{Q_ops}) — штатно для Jasper/Quartz",
                tier="DIAGNOSTIC",
            ))

        # Absolute q/Q *pair* is an emitter invariant for Jasper shells (not
        # mere imbalance). Unknown pairs ⇒ SEQ content-stream reassembly.
        allowed_qq = _QQ_ALLOWED_BY_PROFILE.get(profile_id)
        if allowed_qq is not None:
            pair = (q_ops, Q_ops)
            out.stats["qq_pair"] = pair
            if pair not in allowed_qq:
                allowed = ", ".join(
                    f"{a}/{b}" for a, b in sorted(allowed_qq)
                )
                n_hint = "n=41" if profile_id == "sbp_outgoing" else "n=15"
                out.flags.append(_f(
                    "SBER_CONTENT_QQ_PROFILE",
                    (
                        f"q/Q={q_ops}/{Q_ops} вне корпуса {profile_id} "
                        f"({allowed}; {n_hint}) — чужой clipping/graphics "
                        f"stack в content-stream"
                    ),
                    group="visibility",
                ))

        # Padding comments / post-ET garbage = grammar conflict
        pad_comments = [
            ln for ln in content.split(b"\n")
            if ln.strip().startswith(b"%") and len(ln.strip()) > 12
        ]
        if pad_comments:
            out.flags.append(_f(
                "SBER_CONTENT_OPERATOR_GRAMMAR_CONFLICT",
                f"padding-комментарии в content stream ({len(pad_comments)})",
                group="visibility",
            ))

        skeleton = content_skeleton_hash(pdf_bytes)
        out.stats["content_skeleton"] = skeleton
        # Atlas skeleton is a tiny snapshot (e.g. 4 hashes / 5 jasper samples).
        # New genuine Sber templates always "drift" — never Tier-B / never FAKE.
        # Same lesson as TBANK_/BANK_CONTENT_SKELETON_UNKNOWN on other banks.
        if profile_id and skeleton and not profile_skeleton_known(profile_id, skeleton):
            out.flags.append(_f(
                "SBER_CONTENT_SKELETON_DRIFT",
                f"skeleton {skeleton} вне atlas профиля {profile_id}",
                tier="DIAGNOSTIC",
                group="diagnostics",
            ))
            out.stats["content_skeleton_unknown"] = True

        # Content-stream compressed length is telemetry only: longer FIO/bank
        # strings legitimately grow Flate payload — never HARD on atlas ceiling.
        from ..structure import find_streams, is_content_stream

        best_raw = 0
        best_dec = 0
        for raw, dec in find_streams(pdf_bytes):
            if not dec:
                continue
            if not (is_content_stream(dec) or (b"BT" in dec and b"Tj" in dec)):
                continue
            if len(dec) > best_dec or (len(dec) == best_dec and len(raw) > best_raw):
                best_dec = len(dec)
                best_raw = len(raw)
        out.stats["content_raw_len"] = best_raw
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out

