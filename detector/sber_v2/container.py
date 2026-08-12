"""Container / xref object-graph checks for Sber v2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..structure import validate_incremental_updates, validate_pdf_structure, xref_integrity
from .types import SberFlag

_HARD_STRUCTURE = frozenset({
    "PDF_STRUCTURE_INVALID",
    "MULTIPLE_PDF_HEADERS",
    "TRAILER_INVALID",
    "XREF_OFFSET_INVALID",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
    "BROKEN_OBJECT_STRUCTURE",
    "OBJECT_GRAPH_INCONSISTENT",
    "TRAILING_DATA_AFTER_EOF",
    "MULTIPLE_STARTXREF_PRESENT",
})
_DIAG_STRUCTURE = frozenset({
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
})


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "container") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_xref_object_graph(pdf_bytes: bytes) -> CheckResult:
    """Physical xref/startxref/active object graph — not bytes.count heuristics alone."""
    out = CheckResult()
    try:
        broken, detail = xref_integrity(pdf_bytes)
        out.stats["xref_broken"] = broken
        if broken:
            out.flags.append(_f(
                "SBER_XREF_OBJECT_GRAPH_CONFLICT",
                detail or "нарушена целостность xref/startxref",
            ))
            out.flags.append(_f("XREF_OFFSET_INVALID", detail or "xref offset invalid"))

        s1 = validate_pdf_structure(pdf_bytes)
        out.stats["structure"] = s1.stats
        for code, det in zip(s1.codes, s1.details):
            if code in _DIAG_STRUCTURE:
                out.flags.append(_f(code, det, tier="DIAGNOSTIC"))
            elif code in _HARD_STRUCTURE:
                # Collapse length/decompress into stream module; keep graph codes here.
                if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
                    continue
                if code == "XREF_OFFSET_INVALID" and broken:
                    continue
                mapped = (
                    "SBER_XREF_OBJECT_GRAPH_CONFLICT"
                    if code in ("DUPLICATE_ACTIVE_OBJECT_DEFINITION", "OBJECT_GRAPH_INCONSISTENT")
                    else code
                )
                out.flags.append(_f(mapped, det))

        s2 = validate_incremental_updates(pdf_bytes)
        out.stats["incremental"] = s2.stats
        for code, det in zip(s2.codes, s2.details):
            if code == "TRAILING_DATA_AFTER_EOF":
                last_eof = pdf_bytes.rfind(b"%%EOF")
                if last_eof >= 0:
                    tail = pdf_bytes[last_eof + 5:]
                    if tail.strip(b"\r\n \t"):
                        out.flags.append(_f(code, det))
                    else:
                        out.flags.append(_f(
                            "SBER_EOF_EOL_ONLY",
                            "после %%EOF только EOL — штатно",
                            tier="DIAGNOSTIC",
                        ))
                continue
            if code in _DIAG_STRUCTURE:
                out.flags.append(_f(code, det, tier="DIAGNOSTIC"))
            elif code in _HARD_STRUCTURE:
                out.flags.append(_f(code, det))

        # Active startxref must resolve; multiple startxref already HARD via structure.
        sx_count = len(re.findall(rb"startxref", pdf_bytes))
        out.stats["startxref_count"] = sx_count
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
