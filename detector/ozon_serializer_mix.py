"""OZ-SERIALIZER-MIX-001 — partial content-stream reserialization in m105 cluster."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ozon_m105_profile import (
    RULE_ID,
    _CLUSTER_LITERALS,
    _POST_BT_CANONICAL,
    _split_pre_post,
    claims_ozon_m105_cluster,
    semantic_prefix_matches_cluster,
)
from .structure import content_stream_bytes

HARD_CODE = "OZON_SERIALIZER_MIX_PROVENANCE"

_GLUE_ON_FIRST_LINE = re.compile(
    r"\.23999999\s+0\s+0\s+-\.23999999.*\bcm\b.*\b(q|re|W\*?|n)\b",
    re.I,
)
_EXCESS_ZERO_RE = re.compile(r"(?:-\.\d+|\.\d+|-?\d+\.\d+)")


@dataclass
class SerializerMixFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    expected: str = "m105 line-by-line pre-BT serialization"
    actual: str = ""


@dataclass
class SerializerMixResult:
    flags: list[SerializerMixFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _content_lines(pdf_bytes: bytes) -> list[str]:
    raw = content_stream_bytes(pdf_bytes) or b""
    if not raw:
        return []
    return raw.decode("latin1", "replace").splitlines()


def _glued_pre_bt(pre_lines: list[str]) -> tuple[bool, str]:
    if not pre_lines:
        return False, ""
    first = pre_lines[0].strip()
    if _GLUE_ON_FIRST_LINE.search(first):
        return True, "первая pre-BT строка склеивает cm+q+re+W+n"
    # Fewer physical lines than m105 baseline while semantic spine intact.
    if len(pre_lines) < 161 and len(first) > 60 and " cm " in f" {first} ":
        return True, f"pre-BT укорочен до {len(pre_lines)} строк (эталон m105: 161)"
    return False, ""


def _post_bt_canonical_resume(post_lines: list[str]) -> bool:
    head = tuple(ln.strip() for ln in post_lines[: len(_POST_BT_CANONICAL)])
    return head == _POST_BT_CANONICAL


def _excess_trailing_zeros(pre_lines: list[str]) -> list[str]:
    """Literals with 4+ fractional digits ending in 00+ outside m105 whitelist."""
    blob = " ".join(pre_lines)
    bad: list[str] = []
    for m in _EXCESS_ZERO_RE.finditer(blob):
        lit = m.group(0)
        if lit in _CLUSTER_LITERALS:
            continue
        if "." not in lit:
            continue
        frac = lit.split(".", 1)[1]
        if len(frac) >= 4 and frac.endswith("00"):
            bad.append(lit)
        elif len(frac) >= 6 and frac.endswith("00"):
            bad.append(lit)
    return sorted(set(bad))


def check_ozon_serializer_mix(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> SerializerMixResult:
    """
    Hard only on exact m105 cluster when semantic prefix matches originals but
    physical serialization shows glued pre-BT operators and canonical BT resume.
    """
    out = SerializerMixResult()
    gate = claims_ozon_m105_cluster(pdf_bytes, producer=producer, creator=creator)
    out.stats["m105_gate"] = gate.stats
    if not gate.matched:
        out.stats["skipped"] = gate.reason or "profile_gate"
        return out

    lines = _content_lines(pdf_bytes)
    pre, post, _ = _split_pre_post(lines)
    out.stats["pre_bt_lines"] = len(pre)

    if not semantic_prefix_matches_cluster(pre):
        out.stats["skipped"] = "semantic_prefix_mismatch"
        return out

    glued, glue_detail = _glued_pre_bt(pre)
    out.stats["glued_pre_bt"] = glued
    out.stats["glue_detail"] = glue_detail

    canonical_resume = _post_bt_canonical_resume(post)
    out.stats["post_bt_canonical"] = canonical_resume

    excess = _excess_trailing_zeros(pre)
    out.stats["excess_trailing_zeros"] = excess

    if not glued:
        out.stats["skipped"] = "serialization_canonical"
        return out
    if not canonical_resume:
        out.stats["skipped"] = "post_bt_not_canonical"
        return out

    # Glued prefix + canonical BT boundary is decisive; trailing zeros strengthen evidence.
    detail_parts = [
        glue_detail,
        "на границе BT восстановлена штатная построчная запись m105",
    ]
    if excess:
        detail_parts.append(
            f"нехарактерные конечные нули в pre-BT: {', '.join(excess[:4])}"
        )

    out.flags.append(SerializerMixFlag(
        code=HARD_CODE,
        detail=(
            "статический префикс content stream семантически совпадает с m105-оригиналами, "
            "но физическая сериализация частично пересобрана: "
            + "; ".join(detail_parts)
        ),
        actual=pre[0][:160] if pre else "",
    ))
    return out
