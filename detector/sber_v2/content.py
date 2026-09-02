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

# iText 2.1.7 / Jasper 6.18 identity Tm: operands are integers or 2-decimal
# tokens. 3+ fractional digits = foreign serializer (Python/Java default float).
_JASPER_TM_PROFILES = frozenset({
    "sber_internal_jasper",
    "sbp_outgoing",
    "sbp_request",
})
_TM_IDENTITY_RE = re.compile(
    rb"1 0 0 1 ([+\-]?\d+(?:\.\d+)?) ([+\-]?\d+(?:\.\d+)?) Tm"
)
# Fixed Jasper template rows (*.74). Genuines always emit the 2-decimal token;
# SEQ truncates to *.7 (615.7 / 711.7 on the proton-pass set).
_JASPER_TEMPLATE_Y_CANON = frozenset({
    "204.74", "238.74", "296.74", "304.74", "330.74", "345.74",
    "364.74", "385.74", "398.74", "434.74", "456.74", "475.74",
    "490.74", "524.74", "558.74", "565.74", "601.74", "604.74",
    "615.74", "632.74", "643.74", "697.74", "711.74", "728.74",
})
_JASPER_TEMPLATE_Y_TRUNC = frozenset(
    canon[:-1] for canon in _JASPER_TEMPLATE_Y_CANON
)
_STRING_RE = re.compile(rb"\((?:\\.|[^\\)])*\)")
_HEXSTR_RE = re.compile(rb"<[0-9A-Fa-f\s]+>")


def _frac_digits(token: bytes) -> int:
    if b"." not in token:
        return 0
    return len(token.split(b".", 1)[1])


def _content_without_strings(content: bytes) -> bytes:
    return _HEXSTR_RE.sub(b"<>", _STRING_RE.sub(b"()", content))


def audit_jasper_tm_serialization(
    content: bytes,
    profile_id: str,
) -> list[SberFlag]:
    """HARD: Jasper Tm number spelling that iText 2.1.7 never emits."""
    if profile_id not in _JASPER_TM_PROFILES or not content:
        return []
    flags: list[SberFlag] = []
    stripped = _content_without_strings(content)
    overflow: list[str] = []
    truncated: list[str] = []
    for x, y in _TM_IDENTITY_RE.findall(stripped):
        if _frac_digits(x) >= 3 or _frac_digits(y) >= 3:
            overflow.append(f"{x.decode()} {y.decode()}")
        y_s = y.decode()
        if y_s in _JASPER_TEMPLATE_Y_TRUNC:
            truncated.append(y_s)
    if overflow:
        shown = ", ".join(overflow[:4])
        extra = f" (+{len(overflow) - 4})" if len(overflow) > 4 else ""
        flags.append(_f(
            "SBER_CONTENT_TM_DECIMAL_OVERFLOW",
            (
                f"Tm с ≥3 знаками после точки ({shown}{extra}) — "
                f"iText 2.1.7/Jasper пишет 0 или 2 знака, не 3"
            ),
            group="visibility",
        ))
    if truncated:
        uniq = ", ".join(sorted(set(truncated)))
        flags.append(_f(
            "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED",
            (
                f"Tm.y={uniq} — обрезка корпусного шаблонного ряда *.74 "
                f"(Jasper всегда пишет 2 знака, напр. 615.74 / 711.74)"
            ),
            group="visibility",
        ))
    return flags


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

        tm_flags = audit_jasper_tm_serialization(content, profile_id)
        out.flags.extend(tm_flags)
        out.stats["tm_serialization_hard"] = [f.code for f in tm_flags]

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

