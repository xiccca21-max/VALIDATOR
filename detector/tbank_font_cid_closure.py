"""K-TBANK-FONT-CID-CLOSURE-001 — CID/CMap/W/FontFile2 closure."""

from __future__ import annotations

from dataclasses import dataclass, field

from .font_layers import run_font_layer_checks
from .pdf_forensics import Weight
from .structure import content_stream_bytes
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_spec import check_fontfile2_cid_integrity

RULE_ID = "K-TBANK-FONT-CID-CLOSURE-001"
HARD_CODE = "TBANK_FONT_CID_CLOSURE_VIOLATION"

_CLOSURE_CODES = frozenset({
    "USED_CID_MISSING_FROM_CMAP",
    "USED_CID_MISSING_FROM_W",
    "USED_CID_CMAP_MISMATCH",
    "CMAP_W_MISMATCH",
    "FONTFILE2_CID_MISSING",
    "BROKEN_GLYPH_ZERO_LENGTH",
    "W_MISSING_CID",
    "W_ARRAY_PRETTY_PRINTED",
})


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    profile: str = PROFILE_ID


@dataclass
class CidClosureResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_font_cid_closure(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> CidClosureResult:
    out = CidClosureResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    content = content_stream_bytes(pdf_bytes) or b""
    fl = run_font_layer_checks(pdf_bytes, bank="tbank")
    out.stats["font_layers"] = fl.stats
    for f in fl.flags:
        if f.code in _CLOSURE_CODES and f.weight == Weight.HIGH:
            out.flags.append(HardFlag(code=f.code, detail=f.detail))
        elif f.code in _CLOSURE_CODES and f.code == "W_MISSING_CID":
            out.flags.append(HardFlag(code=f.code, detail=f.detail))

    spec = check_fontfile2_cid_integrity(pdf_bytes, content)
    for sf in spec.flags:
        if sf.code in _CLOSURE_CODES:
            out.flags.append(HardFlag(code=sf.code, detail=sf.detail))

    return out
