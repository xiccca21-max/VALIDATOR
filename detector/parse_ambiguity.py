"""Parser ambiguity HARD — only when two incompatible critical interpretations exist."""

from __future__ import annotations

import re

from .dict_key_conflict import audit_duplicate_critical_dict_keys
from .structural_deep_xref_stream import (
    DeepAuditResult,
    StructFinding,
    audit_xref_deep,
    index_indirect_objects,
)


def audit_parse_ambiguity(pdf_bytes: bytes) -> DeepAuditResult:
    """Emit PDF_CRITICAL_PARSE_AMBIGUITY only with a concrete contradiction detail.

    Duplicate critical-key conflicts that change Contents/Root/Length are already
    emitted by dict_key_conflict. Here we add xref-vs-body disagreements that are
    not already covered by more specific XREF_* codes.
    """
    res = DeepAuditResult()

    # Duplicate object definitions with different body starts → ambiguity
    seen: dict[tuple[int, int], int] = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf_bytes):
        key = (int(m.group(1)), int(m.group(2)))
        if key in seen and seen[key] != m.start():
            # Prefer existing DUPLICATE_ACTIVE_OBJECT_DEFINITION via structure.py;
            # only emit ambiguity when bodies clearly differ at critical keys.
            b1 = pdf_bytes[seen[key] : seen[key] + 400]
            b2 = pdf_bytes[m.start() : m.start() + 400]
            if b"/Contents" in b1 or b"/Contents" in b2 or b"/Length" in b1:
                if b1 != b2:
                    res.add(StructFinding(
                        code="PDF_CRITICAL_PARSE_AMBIGUITY",
                        detail=(
                            f"duplicate object {key[0]} {key[1]} at offsets "
                            f"{seen[key]} and {m.start()} with differing bodies; "
                            f"parsers may resolve different critical values"
                        ),
                        object_number=key[0],
                        generation=key[1],
                        offset=m.start(),
                        expected=str(seen[key]),
                        actual=str(m.start()),
                        parser_stage="parse_ambiguity.dup_obj",
                    ))
        else:
            seen[key] = m.start()

    # If xref maps an object number to offset A but a different object header
    # also claims that number elsewhere without incremental update clarity —
    # covered by XREF_ENTRY_OBJECT_MISMATCH; avoid duplicate unless both fire
    # with distinct detail.
    xref = audit_xref_deep(pdf_bytes)
    mismatch = [f for f in xref.findings if f.code == "XREF_ENTRY_OBJECT_MISMATCH"]
    dups = audit_duplicate_critical_dict_keys(pdf_bytes)
    dict_amb = [f for f in dups.findings if f.code == "PDF_CRITICAL_PARSE_AMBIGUITY"]
    # Already included via orchestrator dict auditor; only add xref+dict combo note
    if mismatch and dict_amb:
        res.add(StructFinding(
            code="PDF_CRITICAL_PARSE_AMBIGUITY",
            detail=(
                f"{mismatch[0].detail}; additionally conflicting dictionary keys: "
                f"{dict_amb[0].detail}"
            ),
            object_number=mismatch[0].object_number,
            offset=mismatch[0].offset,
            parser_stage="parse_ambiguity.xref_plus_dict",
        ))

    res.stats["dup_obj_defs"] = sum(1 for _ in seen)
    _ = index_indirect_objects  # available for future generation-aware paths
    return res
