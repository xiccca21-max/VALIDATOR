"""K-TBANK-RECEIPT-FORMAT-001 — receipt number structure."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .structure import content_stream_bytes
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile

RULE_ID = "K-TBANK-RECEIPT-FORMAT-001"
HARD_CODE = "TBANK_RECEIPT_NUMBER_FORMAT"
_VALID_RE = re.compile(r"^1-\d{3}-\d{3}-\d{3}-\d{3}$")
_LABEL_RE = re.compile(
    r"(?:Квитанция\s*№\s*|квитанция\s*№\s*)([0-9\-]+)",
    re.I,
)
_CS_NUM_RE = re.compile(rb"1-\d{1,3}(?:-\d{1,3}){0,3}")


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    expected: str = "^1-\\d{3}-\\d{3}-\\d{3}-\\d{3}$"
    actual: str = ""
    profile: str = PROFILE_ID


@dataclass
class ReceiptFormatResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _extract_receipt_number(text: str, content: bytes) -> str:
    for line in text.splitlines():
        m = _LABEL_RE.search(line.strip())
        if m:
            return m.group(1).strip()
    m = _LABEL_RE.search(text)
    if m:
        return m.group(1).strip()
    cm = _CS_NUM_RE.search(content)
    if cm:
        return cm.group(0).decode("ascii", "replace")
    return ""


def check_receipt_format(
    pdf_bytes: bytes,
    text: str,
    *,
    producer: str = "",
    creator: str = "",
) -> ReceiptFormatResult:
    out = ReceiptFormatResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    content = content_stream_bytes(pdf_bytes) or b""
    number = _extract_receipt_number(text, content)
    out.stats["receipt_number"] = number
    if not number:
        out.stats["skipped"] = "receipt_number_missing"
        return out

    if _VALID_RE.fullmatch(number):
        out.stats["valid"] = True
        return out

    out.flags.append(HardFlag(
        code=HARD_CODE,
        detail=(
            f"номер квитанции «{number}» не соответствует шаблону "
            f"1-XXX-XXX-XXX-XXX (четыре трёхзначных блока)"
        ),
        actual=number,
    ))
    return out
