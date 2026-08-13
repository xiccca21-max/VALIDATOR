"""Orchestrator for structural deep HARD audits + feature gate."""

from __future__ import annotations

from typing import Any

from .critical_refs import audit_critical_indirect_refs
from .dict_key_conflict import audit_duplicate_critical_dict_keys
from .page_tree_graph import audit_page_tree
from .parse_ambiguity import audit_parse_ambiguity
from .sfnt_math_integrity import audit_sfnt_math
from .structural_deep_xref_stream import (
    ENABLED_STRUCTURAL_HARD,
    DeepAuditResult,
    StructFinding,
    audit_stream_length_contract,
    audit_xref_deep,
)

ALL_NEW_STRUCTURAL_CODES: frozenset[str] = frozenset({
    "XREF_ENTRY_OBJECT_MISMATCH",
    "XREF_GENERATION_MISMATCH",
    "XREF_SUBSECTION_INVALID",
    "XREF_SIZE_CONTRADICTION",
    "XREF_DUPLICATE_LIVE_MAPPING",
    "STREAM_LENGTH_REFERENCE_INVALID",
    "STREAM_LENGTH_TYPE_INVALID",
    "STREAM_LENGTH_BOUNDARY_CONTRADICTION",
    "STREAM_ENDSTREAM_CONTRADICTION",
    "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT",
    "PAGETREE_PARENT_CONTRADICTION",
    "PAGETREE_COUNT_CONTRADICTION",
    "PAGETREE_CYCLE",
    "PAGE_CONTENT_REFERENCE_INVALID",
    "SFNT_TABLE_CHECKSUM_INVALID",
    "SFNT_CHECKSUM_ADJUSTMENT_INVALID",
    "SFNT_DIRECTORY_CONTRADICTION",
    "INDIRECT_REFERENCE_GENERATION_MISMATCH",
    "CRITICAL_INDIRECT_REFERENCE_BROKEN",
    "PDF_CRITICAL_PARSE_AMBIGUITY",
    # existing code reused when deep xref finds out-of-bounds / non-object offset
    "XREF_OFFSET_INVALID",
})


def run_structural_deep_audit(pdf_bytes: bytes) -> DeepAuditResult:
    merged = DeepAuditResult()
    parts = (
        audit_xref_deep(pdf_bytes),
        audit_stream_length_contract(pdf_bytes),
        audit_duplicate_critical_dict_keys(pdf_bytes),
        audit_page_tree(pdf_bytes),
        audit_sfnt_math(pdf_bytes),
        audit_critical_indirect_refs(pdf_bytes),
        audit_parse_ambiguity(pdf_bytes),
    )
    seen: set[tuple[str, str]] = set()
    for part in parts:
        for k, v in part.stats.items():
            merged.stats[k] = v
        for f in part.findings:
            key = (f.code, f.detail[:160])
            if key in seen:
                continue
            seen.add(key)
            merged.add(f)
    merged.stats["findings_total"] = len(merged.findings)
    merged.stats["hard_enabled"] = sorted(ENABLED_STRUCTURAL_HARD)
    merged.stats["hard_fired"] = [f.code for f in merged.hard_findings]
    return merged


def findings_for_policy(pdf_bytes: bytes) -> tuple[list[StructFinding], list[StructFinding], dict[str, Any]]:
    """Return (hard, diagnostic, stats)."""
    res = run_structural_deep_audit(pdf_bytes)
    return res.hard_findings, res.diagnostic_findings, res.stats
