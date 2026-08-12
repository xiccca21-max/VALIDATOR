"""K-TBANK-INFO-KEYWORDS-LEX-001 — /Keywords lexical serialization in /Info."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RULE_ID = "K-TBANK-INFO-KEYWORDS-LEX-001"
HARD_CODE = "TBANK_INFO_KEYWORDS_LEX_MISMATCH"

from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile

_INFO_REF_RE = re.compile(rb"/Info\s+(\d+)\s+0\s+R")


def has_fake_keywords_serialization(info_object_raw: bytes) -> bool:
    """Whitespace/tab/newline between /Keywords and ( → non-bank serializer."""
    return re.search(rb"/Keywords[ \t\r\n]+\(", info_object_raw) is not None


def _info_object_number(pdf_bytes: bytes) -> int | None:
    """Last /Info N 0 R before startxref (active trailer)."""
    sx = pdf_bytes.rfind(b"startxref")
    if sx < 0:
        return None
    refs = list(_INFO_REF_RE.finditer(pdf_bytes[:sx]))
    if not refs:
        return None
    return int(refs[-1].group(1))


def _raw_object(pdf_bytes: bytes, obj_num: int) -> bytes | None:
    pat = re.compile(rb"(\d+)\s+0\s+obj(.*?)endobj", re.DOTALL)
    for m in pat.finditer(pdf_bytes):
        if int(m.group(1)) == obj_num:
            return m.group(0)
    return None


@dataclass
class InfoKeywordsLexResult:
    applies: bool = False
    mismatch: bool = False
    info_object: int = 0
    detail: str = ""
    stats: dict = field(default_factory=dict)


def check_info_keywords_lex(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> InfoKeywordsLexResult:
    """
    K-TBANK-INFO-KEYWORDS-LEX-001:
    bank Jasper/OpenPDF writes /Keywords( with no separator before '('.
    """
    out = InfoKeywordsLexResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "metadata_not_jasper_openpdf"
        return out

    info_num = _info_object_number(pdf_bytes)
    if info_num is None:
        out.stats["skipped"] = "info_ref_missing"
        return out

    info_raw = _raw_object(pdf_bytes, info_num)
    if not info_raw:
        out.stats["skipped"] = "info_object_missing"
        return out

    out.applies = True
    out.info_object = info_num
    out.stats["info_object"] = f"{info_num} 0"

    if b"/Keywords" not in info_raw:
        out.stats["skipped"] = "keywords_missing"
        out.applies = False
        return out

    if not has_fake_keywords_serialization(info_raw):
        out.stats["serialization"] = "canonical"
        return out

    snippet = info_raw[: info_raw.find(b"/Keywords") + 24]
    out.mismatch = True
    out.detail = (
        f"объект /Info {info_num} 0: между /Keywords и ( есть пробел/таб/перевод строки "
        f"(банковский Jasper/OpenPDF пишет /Keywords( без разделителя); "
        f"фрагмент: {snippet.decode('latin1', 'replace')!r}"
    )
    out.stats["serialization"] = "whitespace_before_paren"
    return out
