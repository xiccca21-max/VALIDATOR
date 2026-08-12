"""K-TBANK-FONT-TABLE-INTEGRITY-001 — embedded FontFile2 TTF subset integrity."""

from __future__ import annotations

from dataclasses import dataclass, field

from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_spec import check_glyph_and_font_tables

RULE_ID = "K-TBANK-FONT-TABLE-INTEGRITY-001"
HARD_CODE = "TBANK_FONT_TABLE_INTEGRITY_VIOLATION"

_TABLE_CODES = frozenset({
    "TTF_NUMGLYPHS_MISMATCH",
    "GLYPH_BBOX_IMPOSSIBLE",
    "LOCA_TABLE_BROKEN",
    "TTF_CHECKSUM_ADJUSTMENT_INVALID",
    "TTF_HMTX_COUNT_MISMATCH",
})


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    profile: str = PROFILE_ID


@dataclass
class FontTableIntegrityResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_font_table_integrity(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> FontTableIntegrityResult:
    out = FontTableIntegrityResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    spec = check_glyph_and_font_tables(pdf_bytes)
    out.stats["checks"] = len(spec.flags)
    for sf in spec.flags:
        if sf.code in _TABLE_CODES:
            out.flags.append(HardFlag(code=sf.code, detail=sf.detail))

    return out
