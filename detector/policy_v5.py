"""T-Bank validator policy v5.2: binary Tier A/B/C aggregation.

Tier A is a hard structural contradiction. Tier B is review evidence and can
become FAKE only when independent groups agree. Tier C is analytics only.
The external verdict is always binary: ОРИГИНАЛ/ФЕЙК.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_CODE_RE = re.compile(r"^\[([A-Z0-9_-]+)\]")


@dataclass(frozen=True)
class PolicyFlag:
    flag: str
    code: str
    tier: str
    group: str


# Existing detector codes mapped to the v5.1 trust model. This is deliberately
# conservative: exact-version/profile drift belongs to Tier B/C, not direct FAKE.
TIER_A_CODES: dict[str, str] = {
    "ANALYSIS_NOT_COMPLETED": "analysis_failure",
    # Container ambiguity/corruption
    "PDF_STRUCTURE_INVALID": "container_ambiguity_and_corruption",
    "MULTIPLE_PDF_HEADERS": "container_ambiguity_and_corruption",
    "TRAILER_INVALID": "container_ambiguity_and_corruption",
    "XREF_OFFSET_INVALID": "container_ambiguity_and_corruption",
    "MULTIPLE_STARTXREF_PRESENT": "container_ambiguity_and_corruption",
    "MULTIPLE_EOF_PRESENT": "container_ambiguity_and_corruption",
    "MULTIPLE_XREF_PRESENT": "container_ambiguity_and_corruption",
    "PREV_TRAILER_PRESENT": "container_ambiguity_and_corruption",
    "INCREMENTAL_UPDATE_PRESENT": "container_ambiguity_and_corruption",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION": "container_ambiguity_and_corruption",
    "BROKEN_OBJECT_STRUCTURE": "container_ambiguity_and_corruption",
    "TRAILING_DATA_AFTER_EOF": "container_ambiguity_and_corruption",
    "OBJECT_GRAPH_INCONSISTENT": "container_ambiguity_and_corruption",
    # Streams / active content
    "STREAM_DECOMPRESSION_FAILED": "stream_integrity_and_dos",
    "STREAM_LENGTH_MISMATCH": "stream_integrity_and_dos",
    "JAVASCRIPT_PRESENT": "active_or_hidden_content",
    "ACTIVE_CONTENT_PRESENT": "active_or_hidden_content",
    "OPENACTION_PRESENT": "active_or_hidden_content",
    "DANGEROUS_ACTION_PRESENT": "active_or_hidden_content",
    "EMBEDDED_FILE_PRESENT": "active_or_hidden_content",
    "EMBEDDED_PAYLOAD_PRESENT": "active_or_hidden_content",
    "ACROFORM_PRESENT": "active_or_hidden_content",
    "XFA_PRESENT": "active_or_hidden_content",
    # T-Bank structural/content contradictions
    "TBANK_CONTENT_STREAM_EDIT": "content_and_visual_evasion",
    "TBANK_RUBLE_GLYPH_SPACING": "font_cmap_glyph",
    "TBANK_F3_HASH_MISMATCH": "font_cmap_glyph",
    "TBANK_F3_SIZE_MISMATCH": "font_cmap_glyph",
    "TBANK_F3_NUMGLYPHS": "font_cmap_glyph",
    "TBANK_BT_ET_MISMATCH": "content_and_visual_evasion",
    "TBANK_SBP_STREAM_FIELD_ORDER": "semantic_and_identity",
    # Known bad family, not an originality whitelist.
    "TBANK_KNOWN_GENERATOR_SKELETON": "known_malicious_signature",
    "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE": "known_malicious_signature",
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH": "font_cmap_glyph",
    "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER": "font_cmap_glyph",
    "STATIC_EDITABLE_DIGIT_SUBSET_F2": "font_cmap_glyph",
    # CID/font/glyph hard contradictions
    "USED_CID_MISSING_FROM_CMAP": "font_cmap_glyph",
    "USED_CID_MISSING_FROM_W": "font_cmap_glyph",
    "USED_CID_CMAP_MISMATCH": "font_cmap_glyph",
    "CMAP_W_MISMATCH": "font_cmap_glyph",
    "CMAP_INVALID": "font_cmap_glyph",
    "FONTFILE2_CID_MISSING": "font_cmap_glyph",
    "UNICODE_MAPPING_INVALID": "font_cmap_glyph",
    "BROKEN_GLYPH_ZERO_LENGTH": "font_cmap_glyph",
    "GLYPH_BBOX_IMPOSSIBLE": "font_cmap_glyph",
    "LOCA_TABLE_BROKEN": "font_cmap_glyph",
    "GLYPH_OUTLINE_MISMATCH": "font_cmap_glyph",
    "TEXT_LAYER_INCONSISTENT": "content_and_visual_evasion",
    "TEXT_EXTRACTION_MAPPING_ANOMALY": "content_and_visual_evasion",
    "BROKEN_CYRILLIC_MAPPING": "content_and_visual_evasion",
    "OVERLAY_DETECTED": "content_and_visual_evasion",
    "OVERLAY_TEXT_LAYER": "content_and_visual_evasion",
    # Semantics / identity
    "SBP_CIPHER_MISSING": "semantic_and_identity",
    "SBP_CIPHER_STRUCTURE": "semantic_and_identity",
    "SBP_CIPHER_TIMESTAMP": "semantic_and_identity",
    "SBP_CIPHER_REFERENCE": "semantic_and_identity",
    "BANK_PRODUCER_VERSION_MISMATCH": "semantic_and_identity",
    "MB_SBP_ID_MISSING": "semantic_and_identity",
    "MB_SBP_ID_STRUCTURE": "semantic_and_identity",
    "MB_SBP_ID_TIMESTAMP": "semantic_and_identity",
    "FIELD_FORMAT_INVALID": "semantic_and_identity",
    "STRING_FIELD_STRUCTURE_ANOMALY": "semantic_and_identity",
    "FIELD_ORDER_MISMATCH": "semantic_and_identity",
    "FIELD_SET_MISMATCH": "semantic_and_identity",
    "MISSING_REQUIRED_FIELD_BLOCK": "semantic_and_identity",
    "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS": "semantic_and_identity",
    "LAYOUT_FAMILY_VIOLATION": "semantic_and_identity",
    "LAYOUT_FAMILY_MISSING": "semantic_and_identity",
    "OPERATION_ID_REUSED": "semantic_and_identity",
    "RECEIPT_TEXT_LAYER_MISSING": "content_and_visual_evasion",
    # Raiffeisen iText pdfHTML — CID 0 painted in content (generator splice)
    "RAIF_CONTENT_CID_ZERO": "content_and_visual_evasion",
}


TIER_B_CODES: dict[str, str] = {
    "FOREIGN_PRODUCER": "B6_metadata_version",
    "BANK_PRODUCER_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_PRODUCER_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_CREATOR_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_SUBJECT_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_PAGE_WIDTH": "B2_object_graph_page",
    "TBANK_SHELL_EOF_COUNT": "B1_serializer_container",
    "TBANK_SHELL_PREV_PRESENT": "B1_serializer_container",
    "PDF_MODDATE_EDITED": "B6_metadata_version",
    "TTF_NUMGLYPHS_MISMATCH": "B5_source_fonts",
    "TTF_CHECKSUM_ADJUSTMENT_INVALID": "B5_source_fonts",
    "TTF_HEAD_ANOMALY": "B5_source_fonts",
    "UNUSED_CID_PRESENT": "B5_source_fonts",
    "CMAP_EXTRA_SYMBOLS": "B5_source_fonts",
    "W_ARRAY_PRETTY_PRINTED": "B1_serializer_container",
    "W_ARRAY_SERIALIZATION_ANOMALY": "B1_serializer_container",
}


TIER_C_CODES = frozenset({
    "TBANK_CHANNEL_SKELETON_UNKNOWN",
    "TBANK_CONTENT_SKELETON_UNKNOWN",
    "TBANK_REASSEMBLY_FORGERY",
    "TBANK_LAYERED_PROFILE_FORGERY",
    "TBANK_RENDER_FOREIGN_ROWS",
    "TBANK_FONT_RENDER_FORGERY",
    "TBANK_RENDER_STRUCTURAL_FORGERY",
    "FF2_SUBSET_UNKNOWN",
    "PROFILE_CLUSTER_OUTLIER",
    "CONTENT_STREAM_PROFILE_MISMATCH",
    "TBANK_TEMPLATE_HEIGHT_UNKNOWN",
    "TBANK_TEMPLATE_HEIGHT_MISMATCH",
    "TBANK_TEMPLATE_STREAM_SIZE",
    "TBANK_TEMPLATE_OPERATOR_COUNT",
    "TBANK_TEMPLATE_LABEL_DRIFT",
    "TBANK_F1_NUMGLYPHS",
    "TBANK_F2_NUMGLYPHS",
    "TBANK_F1_HMTX_DRIFT",
    "TBANK_F2_HMTX_DRIFT",
    "TBANK_F1_HEAD_DRIFT",
    "TBANK_F2_HEAD_DRIFT",
    "TBANK_F1_MAXP_DRIFT",
    "TBANK_F2_MAXP_DRIFT",
    "TBANK_F1_W_ARRAY_UNKNOWN",
    "TBANK_F2_W_ARRAY_UNKNOWN",
})


def flag_code(flag: str) -> str:
    match = _CODE_RE.match(flag or "")
    return match.group(1) if match else ""


def classify_flag(flag: str) -> PolicyFlag | None:
    code = flag_code(flag)
    if not code:
        return None
    if code in TIER_A_CODES:
        return PolicyFlag(flag, code, "A", TIER_A_CODES[code])
    if code in TIER_B_CODES:
        return PolicyFlag(flag, code, "B", TIER_B_CODES[code])
    if code in TIER_C_CODES:
        return PolicyFlag(flag, code, "C", "analytics")
    if code.startswith("A-"):
        return PolicyFlag(flag, code, "A", code.split("-", 2)[1] if "-" in code else "tier_a")
    if code.startswith("B-"):
        return PolicyFlag(flag, code, "B", code.rsplit("-", 1)[0])
    if code.startswith("C-"):
        return PolicyFlag(flag, code, "C", "analytics")
    return None


def aggregate_policy(flags: list[str]) -> dict:
    """Return v5.2 binary verdict evidence without hiding diagnostics."""
    classified = [pf for f in flags if (pf := classify_flag(f))]
    tier_a = [pf for pf in classified if pf.tier == "A"]
    tier_b = [pf for pf in classified if pf.tier == "B"]
    tier_c = [pf for pf in classified if pf.tier == "C"]
    b_groups = sorted({pf.group for pf in tier_b})

    verdict = "ФЕЙК" if tier_a or len(b_groups) >= 2 else "ЧИСТО"

    return {
        "verdict": verdict,
        "tier_a_flags": [pf.flag for pf in tier_a],
        "tier_b_flags": [pf.flag for pf in tier_b],
        "tier_c_flags": [pf.flag for pf in tier_c],
        "tier_b_groups": b_groups,
    }
