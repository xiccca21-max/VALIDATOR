"""Critical indirect reference generation/existence contract."""

from __future__ import annotations

import re

from .structural_deep_xref_stream import (
    DeepAuditResult,
    StructFinding,
    index_indirect_objects,
)

_CRITICAL_REF_PATTERNS: list[tuple[str, re.Pattern[bytes]]] = [
    ("Root", re.compile(rb"/Root\s+(\d+)\s+(\d+)\s+R")),
    ("Pages", re.compile(rb"/Pages\s+(\d+)\s+(\d+)\s+R")),
    ("Parent", re.compile(rb"/Parent\s+(\d+)\s+(\d+)\s+R")),
    ("Contents", re.compile(rb"/Contents\s+(\d+)\s+(\d+)\s+R")),
    ("Resources", re.compile(rb"/Resources\s+(\d+)\s+(\d+)\s+R")),
    ("Font", re.compile(rb"/Font\s+(\d+)\s+(\d+)\s+R")),
    ("FontDescriptor", re.compile(rb"/FontDescriptor\s+(\d+)\s+(\d+)\s+R")),
    ("FontFile2", re.compile(rb"/FontFile2\s+(\d+)\s+(\d+)\s+R")),
    ("FontFile3", re.compile(rb"/FontFile3\s+(\d+)\s+(\d+)\s+R")),
    ("FontFile", re.compile(rb"/FontFile\s+(\d+)\s+(\d+)\s+R")),
    ("XObject", re.compile(rb"/XObject\s+(\d+)\s+(\d+)\s+R")),
    ("Length", re.compile(rb"/Length\s+(\d+)\s+(\d+)\s+R")),
]


def audit_critical_indirect_refs(pdf_bytes: bytes) -> DeepAuditResult:
    res = DeepAuditResult()
    index = index_indirect_objects(pdf_bytes)
    by_num: dict[int, set[int]] = {}
    for n, g in index:
        by_num.setdefault(n, set()).add(g)

    checked = 0
    for label, pat in _CRITICAL_REF_PATTERNS:
        for m in pat.finditer(pdf_bytes):
            n, g = int(m.group(1)), int(m.group(2))
            checked += 1
            if (n, g) in index:
                continue
            if n in by_num:
                res.add(StructFinding(
                    code="INDIRECT_REFERENCE_GENERATION_MISMATCH",
                    detail=(
                        f"/{label} {n} {g} R — object {n} exists with gens "
                        f"{sorted(by_num[n])} but not generation {g}"
                    ),
                    object_number=n,
                    generation=g,
                    expected=f"{n} {g} R",
                    actual=f"gens={sorted(by_num[n])}",
                    parser_stage=f"critical_refs.{label}",
                ))
            else:
                res.add(StructFinding(
                    code="CRITICAL_INDIRECT_REFERENCE_BROKEN",
                    detail=f"/{label} {n} {g} R — object missing",
                    object_number=n,
                    generation=g,
                    expected=f"{n} {g} R",
                    actual="missing",
                    parser_stage=f"critical_refs.{label}",
                ))
    res.stats["critical_refs_checked"] = checked
    return res
