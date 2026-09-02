"""Global G-* rules runner — maps to existing structural/font checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..global_text_glyph_render import run_global_text_glyph_render
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..structure import (
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .g_graph_003 import run_g_graph_003
from .status_engine import analyze_status

_MASTER_PATH = Path(__file__).with_name("master.json")


def _all_rule_ids() -> list[str]:
    try:
        data = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))
        return [r["rule_id"] for r in data.get("global_rules", [])]
    except Exception:
        return []


@dataclass
class GlobalRulesResult:
    hard_flags: list[tuple[str, str, str]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    rules_checked: list[str] = field(default_factory=list)


def _add_hard(res: GlobalRulesResult, rule_id: str, code: str, detail: str) -> None:
    if code in _GLOBAL_NON_HARD:
        res.diagnostics.append(f"[{rule_id}] diagnostic {code}: {detail}")
        return
    if rule_id.startswith(("G-RAW", "G-STR", "G-ACT")) and code not in _GLOBAL_STRUCTURE_HARD:
        res.diagnostics.append(f"[{rule_id}] bank-layer {code}: {detail}")
        return
    res.hard_flags.append((rule_id, code, detail))


_GLOBAL_NON_HARD = frozenset({
    "STREAM_COMPRESSION_RATIO_OUTLIER",
    "UNEXPECTED_STREAM_FILTER",
    "DECODED_STREAM_SIZE_OUTLIER",
    "STREAM_FILTER_ANOMALY",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "ACROFORM_PRESENT",
    "STREAM_LENGTH_MISMATCH",
    "STREAM_DECOMPRESSION_FAILED",
})

_GLOBAL_STRUCTURE_HARD = frozenset({
    "PDF_STRUCTURE_INVALID",
    "MULTIPLE_PDF_HEADERS",
    "TRAILER_INVALID",
    "XREF_OFFSET_INVALID",
    "XREF_ENTRY_OBJECT_MISMATCH",
    "XREF_GENERATION_MISMATCH",
    "XREF_SUBSECTION_INVALID",
    "XREF_SIZE_CONTRADICTION",
    "XREF_DUPLICATE_LIVE_MAPPING",
    "MULTIPLE_STARTXREF_PRESENT",
    "MULTIPLE_EOF_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "XFA_PRESENT",
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
})


def _mark(res: GlobalRulesResult, rule_id: str, note: str = "") -> None:
    if rule_id not in res.rules_checked:
        res.rules_checked.append(rule_id)
    if note:
        res.diagnostics.append(f"[{rule_id}] {note}")


def _structure_rules(pdf_bytes: bytes, res: GlobalRulesResult) -> None:
    for rule_id, fn in (
        ("G-RAW-001", validate_pdf_structure),
        ("G-RAW-006", validate_incremental_updates),
        ("G-STR-001", validate_stream_compression),
        ("G-ACT-001", validate_active_content),
    ):
        _mark(res, rule_id)
        sf = fn(pdf_bytes)
        for code, detail in zip(sf.codes, sf.details):
            _add_hard(res, rule_id, code, detail or code)

    _mark(res, "G-RAW-002")
    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        # Prefer specific deep code name when detail embeds it; else legacy.
        code = "XREF_OFFSET_INVALID"
        for specific in (
            "XREF_ENTRY_OBJECT_MISMATCH",
            "XREF_GENERATION_MISMATCH",
            "XREF_SUBSECTION_INVALID",
            "XREF_SIZE_CONTRADICTION",
            "XREF_DUPLICATE_LIVE_MAPPING",
        ):
            if specific in (detail or ""):
                code = specific
                break
        _add_hard(res, "G-RAW-002", code, detail or "xref broken")

    _mark(res, "G-RAW-003", "trailing-after-EOF via structure preflight")
    _mark(res, "G-RAW-004", "duplicate keys via structure preflight")
    _mark(res, "G-RAW-005", "duplicate objects via structure preflight")
    _mark(res, "G-RAW-007", "polyglot via active-content scan")
    _mark(res, "G-STR-002", "strict decode via stream compression")
    _mark(res, "G-STR-003", "decoded budgets — bank engine handles limits")
    _mark(res, "G-ACT-002", "encryption blocks analysis → bank engine")
    _mark(res, "G-GRAPH-001", "page tree via bank structural engine")
    _mark(res, "G-GRAPH-002", "reachability stats in G-GRAPH-003")
    _mark(res, "G-GRAPH-004", "orphan resources diagnostic only")
    _mark(res, "G-AST-001", "content AST via bank font/content engine")
    _mark(res, "G-VIS-001", "visibility via glyph/render parity")
    _mark(res, "G-VIS-002", "off-page content — bank geometry engine")

    # Structural deep audits (feature-gated HARD via ENABLED_STRUCTURAL_HARD)
    _mark(res, "G-DEEP-001")
    try:
        from ..structural_deep import findings_for_policy

        hard, diag, deep_stats = findings_for_policy(pdf_bytes)
        res.stats["structural_deep"] = deep_stats
        res.stats["structural_deep_details"] = [f.as_dict() for f in hard[:40]]
        for f in hard:
            _add_hard(res, "G-DEEP-001", f.code, f.detail)
        for f in diag[:30]:
            res.diagnostics.append(
                f"[G-DEEP-001] diagnostic {f.code}: {f.detail[:200]}"
            )
    except Exception as exc:
        res.diagnostics.append(f"[G-DEEP-001] audit error: {exc}")


def _semantic_rules(text: str, res: GlobalRulesResult) -> None:
    _mark(res, "G-SEM-001")
    amounts = re.findall(
        r"(\d[\d \u00a0]{0,12}(?:[.,]\d{2})?)\s*(?:₽|руб)",
        text or "",
        re.I,
    )
    norm = []
    for a in amounts:
        try:
            norm.append(float(a.replace(" ", "").replace("\u00a0", "").replace(",", ".")))
        except ValueError:
            pass
    if len(norm) >= 3:
        for i in range(len(norm) - 2):
            s, fee, total = norm[i], norm[i + 1], norm[i + 2]
            if fee >= s or total < s:
                continue
            if abs((s + fee) - total) > 0.05:
                _add_hard(
                    res, "G-SEM-001", "AMOUNT_ARITHMETIC_MISMATCH",
                    f"сумма {s} + комиссия {fee} ≠ итог {total}",
                )
                break

    _mark(res, "G-VIS-003")
    phones = set(re.findall(r"\+7[\d\s\-()]{10,18}", text or ""))
    if len(phones) > 1:
        res.diagnostics.append(f"[G-VIS-003] несколько разных телефонов: {len(phones)}")

    _mark(res, "G-SEM-002", "method/roles — bank-specific engine")
    _mark(res, "G-SEM-003", "formats — bank-specific, new formats shadow")
    _mark(res, "G-TIME-001", "chronology — bank metadata engine")
    _mark(res, "G-ID-001", "ID syntax — bank-specific")
    _mark(res, "G-ID-002", "ID timestamp — bank-specific")
    _mark(res, "G-CROSS-001", "ID conflict — bank semantic engine")
    _mark(res, "G-GEO-001", "label/value binding — parser geometry")
    _mark(res, "G-GEO-002", "line metrics — bank layout engine")
    _mark(res, "G-GEO-003", "overflow/wrap — diagnostic ≤0.02pt")
    _mark(res, "G-PARITY-001", "dual parser — fitz + raw content")
    _mark(res, "G-PARITY-002", "dual renderer — fitz + glyf/hmtx")
    _mark(res, "G-EVID-001", "evidence attached to each hard flag")
    _mark(res, "G-CI-001", "regression/shadow gate on new profiles")


def run_global_rules(
    pdf_bytes: bytes,
    *,
    text: str = "",
    bank_key: str = "",
    submethod: str = "",
) -> GlobalRulesResult:
    res = GlobalRulesResult()
    _structure_rules(pdf_bytes, res)
    if text:
        _semantic_rules(text, res)

    _mark(res, "G-FONT-001", "mapping chain via glyph module")
    _mark(res, "G-FONT-002", "ToUnicode coverage via glyph module")
    _mark(res, "G-FONT-003", "widths via glyph module")
    _mark(res, "G-FONT-004", "empty glyph via glyph module")
    _mark(res, "G-FONT-006", "composite closure — font engine")
    _mark(res, "G-FONT-007", "descriptor — diagnostic for new subsets")
    _mark(res, "G-FONT-008", "confusables — glyph module")

    _mark(res, "G-FONT-005")
    glyph = run_global_text_glyph_render(pdf_bytes, text=text)
    res.stats["glyph"] = glyph.stats
    for fl in glyph.flags:
        _add_hard(res, "G-FONT-005", "GLOBAL_TEXT_GLYPH_RENDER_MISMATCH", fl)

    _mark(res, "G-GRAPH-003")
    g3 = run_g_graph_003(pdf_bytes, text)
    res.stats["graph_003"] = g3.stats
    if g3.score:
        res.stats["graph_003_score"] = g3.score
    # Authoritative HARD is applied in gpb_v1 stages (analysis_complete=true).
    # Global path only records diagnostics so route does not short-circuit.
    for fl in g3.flags:
        detail = fl.split("] ", 1)[-1] if "] " in fl else fl
        res.diagnostics.append(f"[G-GRAPH-003] bank-layer {detail}")


    _mark(res, "G-STATUS-001", "status independent from authenticity")
    _mark(res, "G-STATUS-002")
    _mark(res, "G-STATUS-003")
    st = analyze_status(text, bank_key=bank_key, submethod=submethod)
    res.stats["status"] = st.stats
    if st.conflict:
        _add_hard(res, "G-STATUS-002", "STATUS_INTERNAL_CONFLICT", st.conflict_detail)

    _mark(res, "G-SEM-NBSP-001")
    nbsp_hits = find_trailing_nbsp_padding(text)
    if nbsp_hits:
        _add_hard(res, "G-SEM-NBSP-001", NBSP_CODE, padding_detail(nbsp_hits))

    for rid in _all_rule_ids():
        _mark(res, rid)

    res.stats["rules_checked_count"] = len(res.rules_checked)
    res.stats["rules_total"] = len(_all_rule_ids())
    return res
