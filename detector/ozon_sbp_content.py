"""Ozon SBP hard checks — content, cipher, cross-bank leakage (T-Bank-style)."""

from __future__ import annotations

import re

from dataclasses import dataclass, field

from .ozon_profiles import (
    check_amount_display_format,
    is_skia_chromium_profile,
)
from .ozon_sbp_cipher import validate_ozon_sbp_cipher

# T-Bank Jasper/OpenPDF route block. Confirmed Ozon Skia forgeries (sbp.pdf /
# sbp1.pdf / фейк1) splice G100/G101 into the tail; clean Ozon originals use
# routes 00/B1 only. Marker 1791103 is an optional stronger T-Bank pin.
_TBANK_TAIL_BLOCK_RE = re.compile(r"G10[01]")
_TBANK_TAIL_MARKER = "1791103"


@dataclass
class OzonSbpFlag:
    code: str
    detail: str
    rule_id: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class OzonSbpResult:
    flags: list[OzonSbpFlag] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(
        self,
        code: str,
        detail: str,
        *,
        rule_id: str = "",
        expected: str = "",
        actual: str = "",
    ) -> None:
        self.flags.append(OzonSbpFlag(
            code, detail, rule_id=rule_id or code,
            expected=expected, actual=actual,
        ))


def _check_cross_bank_tail(opid: str, res: OzonSbpResult) -> None:
    tail = opid[11:32]
    res.stats["sbp_tail"] = tail
    block_m = _TBANK_TAIL_BLOCK_RE.search(tail)
    has_marker = _TBANK_TAIL_MARKER in tail
    if not block_m:
        return
    block = block_m.group(0)
    res.stats["cross_bank_g10_block"] = block
    res.stats["cross_bank_tbank_marker"] = has_marker
    extra = f" + {_TBANK_TAIL_MARKER}" if has_marker else ""
    res.add(
        "OZON_SBP_ID_CROSS_BANK_TAIL",
        f"хвост СБП-ID содержит блок T-Bank Jasper-профиля "
        f"({block}{extra}) при заявленном Ozon/Skia чеке; "
        f"у Ozon наблюдаются route 00/B1, не G100/G101; tail={tail}",
        rule_id="K-OZON-SBP-CROSS-BANK-001",
        expected="Ozon SBP route ∈ {00, B1}",
        actual=tail,
    )


def validate_ozon_sbp_receipt(
    opid: str,
    text: str,
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> OzonSbpResult:
    """Full Ozon SBP validation for current Skia/Chromium profile."""
    out = OzonSbpResult()
    skia = is_skia_chromium_profile(producer, creator)
    out.stats["skia_chromium"] = skia

    if skia:
        for label, raw in check_amount_display_format(text):
            out.add(
                "OZON_AMOUNT_FORMAT_INVALID",
                f"поле «{label}»: «{raw}» не соответствует банковскому формату "
                f"(группы тысяч через пробел: «9 500 ₽», не «9500 ₽»)",
                rule_id="K-OZON-AMOUNT-FORMAT-001",
                expected=r"^(?:0|[1-9]\d{0,2}(?: \d{3})*) ₽$",
                actual=raw,
            )

    cipher = validate_ozon_sbp_cipher(opid or "", text)
    out.stats["cipher"] = cipher.stats
    for cf in cipher.flags:
        out.add(cf.code, cf.detail, rule_id=cf.rule_id)

    if opid and skia and len(opid) == 32:
        _check_cross_bank_tail(opid, out)

    return out
