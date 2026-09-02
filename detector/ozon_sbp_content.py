"""Ozon SBP hard checks — content, cipher, cross-bank leakage (T-Bank-style)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ozon_profiles import (
    check_amount_display_format,
    is_skia_chromium_profile,
)
from .ozon_sbp_cipher import validate_ozon_sbp_cipher


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

    return out
