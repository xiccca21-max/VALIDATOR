"""Shared Jasper/OpenPDF IB/Receipt profile gate for serialization hard rules."""

from __future__ import annotations

import re

PROFILE_ID = "jasper_6.20.3_openpdf_1.3.30_ib_receipt"

_JASPER_CREATOR_RE = re.compile(
    r"JasperReports Library version 6\.20\.3",
    re.I,
)
_OPENPDF_PRODUCER_RE = re.compile(
    r"OpenPDF 1\.3\.30\.jaspersoft\.2",
    re.I,
)
_SUBJECT_MARKERS = (b"/reports/IB/Receipt", b"IB/Receipt")


def claims_confirmed_tbank_profile(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> bool:
    """Creator 6.20.3 + Producer OpenPDF 1.3.30 + Subject /reports/IB/Receipt."""
    if not any(marker in pdf_bytes for marker in _SUBJECT_MARKERS):
        return False
    if creator and _JASPER_CREATOR_RE.search(creator):
        if producer and _OPENPDF_PRODUCER_RE.search(producer):
            return True
    for pat in (rb"/Creator\s*\(([^)]*)\)", rb"/Creator\s*<([^>]*)>"):
        m = re.search(pat, pdf_bytes)
        if not m:
            continue
        c = (m.group(1) or b"").decode("latin1", "replace")
        if not _JASPER_CREATOR_RE.search(c):
            continue
        for pp in (rb"/Producer\s*\(([^)]*)\)", rb"/Producer\s*<([^>]*)>"):
            pm = re.search(pp, pdf_bytes)
            if pm:
                p = (pm.group(1) or b"").decode("latin1", "replace")
                if _OPENPDF_PRODUCER_RE.search(p):
                    return True
    return False
