"""Dual-parser field parity for Sber v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

try:
    import fitz
except ImportError:
    fitz = None

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        PdfReader = None  # type: ignore

from ..sber_profiles import (
    extract_internal_document,
    extract_legacy_document,
    extract_sbp_opid,
)
from .types import SberFlag


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD") -> SberFlag:
    return SberFlag(
        code=code, detail=detail, tier=tier, group="parity", rule_id=code,
    )


def _fitz_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text() if doc.page_count else ""
    doc.close()
    return text


def _pypdf_text(pdf_bytes: bytes) -> str:
    if not PdfReader:
        return ""
    reader = PdfReader(BytesIO(pdf_bytes))
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def _raw_sbp_from_content(pdf_bytes: bytes) -> str | None:
    import re
    from ..structure import content_stream_bytes
    content = content_stream_bytes(pdf_bytes) or b""
    # hex strings and literal strings may embed opid fragments
    compact = re.sub(rb"\s+", b"", content)
    m = re.search(rb"([AB][0-9A-Z]{31})", compact)
    if m:
        return m.group(1).decode("ascii", "replace")
    # Try latin1 from PDF text operators
    textish = content.decode("latin1", "replace")
    m2 = re.search(r"([AB][0-9A-Z]{31})", re.sub(r"\s+", "", textish))
    return m2.group(1) if m2 else None


def check_dual_parser_parity(pdf_bytes: bytes, text_fitz: str = "") -> CheckResult:
    out = CheckResult()
    try:
        t_fitz = text_fitz or _fitz_text(pdf_bytes)
        t_pypdf = _pypdf_text(pdf_bytes)
        out.stats["fitz_len"] = len(t_fitz)
        out.stats["pypdf_len"] = len(t_pypdf)

        extractors = (
            ("sbp_id", extract_sbp_opid),
            ("legacy_doc", extract_legacy_document),
            ("internal_doc", extract_internal_document),
        )
        for name, fn in extractors:
            a = fn(t_fitz)
            b = fn(t_pypdf) if t_pypdf else None
            out.stats[f"{name}_fitz"] = a
            out.stats[f"{name}_pypdf"] = b
            if a and b and a != b:
                out.flags.append(_f(
                    "SBER_DUAL_PARSER_FIELD_PARITY",
                    f"{name}: fitz «{a}» ≠ pypdf «{b}»",
                ))

        # Raw content vs fitz for SBP when both present
        raw = _raw_sbp_from_content(pdf_bytes)
        fitz_sbp = extract_sbp_opid(t_fitz)
        out.stats["sbp_raw"] = raw
        if raw and fitz_sbp and raw != fitz_sbp:
            out.flags.append(_f(
                "SBER_DUAL_PARSER_FIELD_PARITY",
                f"sbp_id: raw content «{raw}» ≠ fitz «{fitz_sbp}»",
            ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
