"""Sber v2 rule tiers — HARD / KNOWN / Tier-B / IGNORE."""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^\[([A-Z0-9_-]+)\]")

HARD_CODES: frozenset[str] = frozenset({
    "ANALYSIS_NOT_COMPLETED",
    "NOT_SBER_RECEIPT",
    # Container / object graph
    "SBER_XREF_OBJECT_GRAPH_CONFLICT",
    "PDF_STRUCTURE_INVALID",
    "MULTIPLE_PDF_HEADERS",
    "TRAILER_INVALID",
    "XREF_OFFSET_INVALID",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
    "BROKEN_OBJECT_STRUCTURE",
    "OBJECT_GRAPH_INCONSISTENT",
    "TRAILING_DATA_AFTER_EOF",
    "MULTIPLE_STARTXREF_PRESENT",
    # Streams
    "SBER_STREAM_INTEGRITY_VIOLATION",
    "STREAM_DECOMPRESSION_FAILED",
    "STREAM_LENGTH_MISMATCH",
    "UNEXPECTED_STREAM_FILTER",
    # Active content
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "ACROFORM_PRESENT",
    "XFA_PRESENT",
    # Content / visibility
    "SBER_CONTENT_OPERATOR_GRAMMAR_CONFLICT",
    "SBER_CONTENT_QQ_PROFILE",
    "SBER_CONTENT_TM_DECIMAL_OVERFLOW",
    "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED",
    "SBER_BT_ET_MISMATCH",
    "SBER_DUAL_PARSER_FIELD_PARITY",
    "SBER_OVERLAY_HIDDEN_TEXT_LAYER",
    "SBER_LABEL_VALUE_GEOMETRY_CONFLICT",
    "TEXT_LAYER_INCONSISTENT",
    "BROKEN_CYRILLIC_MAPPING",
    "TEXT_EXTRACTION_MAPPING_ANOMALY",
    "RECEIPT_TEXT_LAYER_MISSING",
    # Fonts
    "SBER_FONT_LAYER_CONTAMINATION",
    "USED_CID_MISSING_FROM_CMAP",
    "USED_CID_MISSING_FROM_W",
    "CMAP_W_MISMATCH",
    "CMAP_INVALID",
    "FONTFILE2_MISSING",
    "MISSING_FONT_OBJECT",
    "USED_CID_EMPTY_GLYPH",
    "GLYPH_SLOT_TRANSPLANT",
    "GLYPH_OUTLINE_MISMATCH",
    "SBER_FONT_CID_CLOSURE_VIOLATION",
    "SBER_FONT_W_QUANTIZER_MISMATCH",
    "SBER_FONT_REVERSE_GLYPH_CLOSURE",
    "SBER_FONT_GLYF_UNIQ_LENS",
    "SBER_FONT_GLYF_NONEMPTY_COUNT",
    # Ghost loca slots / hmtx vocabulary: always equal on sbp_outgoing genuines;
    # SEQ pads zero-contour stubs and drifts advance set (0 FP on corpus).
    "SBER_FONT_GLYF_LOCA_CONTOUR_MISMATCH",
    "SBER_FONT_GLYF_CONTOUR_NONEMPTY",
    "SBER_FONT_HMTX_UNIQ_ADVANCES",
    # sber_internal_jasper subset packing floors (nonempty≥75, composites≥14)
    "SBER_INTERNAL_GLYF_NONEMPTY_FLOOR",
    "SBER_INTERNAL_GLYF_COMPOSITE_FLOOR",
    # SBER_FONTFILE2_DEC_PROFILE demoted — exact FF2 size set n=15 ≠ all
    # genuine internal subsets (e.g. 55596 B on live bank receipt).
    "SBER_FONTFILE2_RAW_TOO_SMALL",
    "SBER_STATIC_TEXT_ADVANCE_MISMATCH",
    "SBER_STATIC_LABEL_OUTLINE_MISMATCH",
    "SBER_SEPARATOR_ADVANCE_MISMATCH",
    "SBER_HEADER_DATE_CENTER_MISMATCH",
    "SBER_SBP_MARKER_INVALID",
    "SBER_AMOUNT_RUBLE_SPACING_INVALID",
    # Glyph ink spacing (learned on Jasper genuines): no overlap, no huge gaps.
    "SBER_GLYPH_INK_OVERLAP",
    "SBER_GLYPH_INK_WIDE_GAP",
    "SBER_GLYPH_INK_MAX_TOO_LOW",
    "SBER_GLYPH_INK_MIN_OUT_OF_BAND",
    # SBER_GLYPH_INK_MAX_PROFILE demoted — discrete ink_max atlas n=15 FP
    # on genuine internal (462 ∉ {461,561,599}).
    "SBER_GLYPH_PAIRS_TOO_FEW",
    "SBER_CONTENT_TC_TRACKING",
    "SBER_CONTENT_TW_WORD_SPACING",
    "SBER_CONTENT_TJ_KERNING",
    "SBER_HEADER_TRAILING_PADDING",
    "SBER_HEADER_DATE_LEADING_WHITESPACE",
    "SBER_HEADER_DATE_TRAILING_WHITESPACE",
    "SBER_FIO_TRAILING_PADDING",
    "TEXT_TRAILING_NBSP_PADDING",
    "SBER_RECIPIENT_INITIAL_PUNCTUATION",
    # Labels share one left vertical inside a receipt (relative spread only).
    "SBER_LABEL_LEFT_EDGE_SPREAD",
    # Size envelopes demoted — small atlas / future genuine growth ≠ FAKE
    # Embedded FontFile2 reassembly forensics
    "SBER_REBUILD_RAW_NUL_IN_TEXT_001",
    "SBER_REBUILD_TEXT_OPERAND_CONTROL_BYTE_005",
    "SBER_REBUILD_CONTENT_FONT_CROSSPRODUCT_002",
    "SBER_REBUILD_USED_GLYPH_SUBSET_CARDINALITY_003",
    "SBER_REBUILD_JASPER_OBJECT_FAMILY_CONFLICT_004",
    # Semantics
    "SBER_LINKED_SEMANTIC_TUPLE_CONFLICT",
    "SBER_REQUIRED_FIELD_MISSING",
    "SBER_SBP_LINKED_TUPLE_CONFLICT",
    "SBER_SBP_TIMESTAMP_MISMATCH",
    "SBER_AMOUNT_ARITHMETIC_MISMATCH",
    "SBER_PHONE_DEF_NOT_MOBILE",
    "SBER_SBP_RECIPIENT_FIO_FORMAT",
    "SBER_SBP_SENDER_FIO_FORMAT",
    "SBER_AMOUNT_LEADING_WHITESPACE",
    "SBER_FIO_LEADING_WHITESPACE",
    "SBER_BANK_NAME_TRAILING_WHITESPACE",
    "FIELD_FORMAT_INVALID",
    "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS",
    # Cross-document
    "SBER_CROSS_DOCUMENT_IDENTITY_CONFLICT",
    "OPERATION_ID_REUSED",
})

KNOWN_FAKE_CODES: frozenset[str] = frozenset({
    "SBER_KNOWN_FAKE_SIGNATURE",
    "SBER_REASSEMBLED_BANK_ASSETS",
    # SBER_KNOWN_FAKE_FONTFILE2 removed — novelty FontFile2 sha pins caused genuine FPs
})

SUPPORTING_GROUPS: dict[str, str] = {
    "SBER_LAYOUT_DRIFT": "B2_layout_content",
    "STREAM_COMPRESSION_RATIO_OUTLIER": "B1_serializer_container",
    "DECODED_STREAM_SIZE_OUTLIER": "B1_serializer_container",
    "STREAM_FILTER_ANOMALY": "B1_serializer_container",
    "SBER_SERIALIZER_PROFILE_SHIFT": "B1_serializer_container",
    "SBER_METADATA_PROFILE_SHIFT": "B3_metadata_profile",
    "PDF_MODDATE_EDITED": "B3_metadata_profile",
    "SBER_STATIC_ASSET_PROFILE_SHIFT": "B4_static_assets",
    "SBER_FONT_SUBSETTER_PROFILE_SHIFT": "B4_font_subsetter",
    "SBER_SBP_EMPIRICAL_PROFILE": "B5_sbp_empirical",
    "SBER_SBP_TAIL_UNKNOWN": "B5_sbp_empirical",
    "SBER_SBP_MARKER_UNKNOWN": "B5_sbp_empirical",
    "SBER_CROSS_DOCUMENT_WEAK_MATCH": "B6_cross_document_weak",
}

IGNORED_CODES: frozenset[str] = frozenset({
    "SBER_CONTENT_SKELETON_DRIFT",
    "SBER_NEW_PRODUCER_OBSERVATION",
    "SBER_NEW_FONTFILE2_SHA",
    "SBER_NEW_PAGE_SIZE",
    "SBER_NEW_IMAGE_BUNDLE",
    "SBER_NEW_SUBSET_PREFIX",
    "SBER_FIO_ALPHABET_RUN",
    "SBER_FIO_CONSONANT_RUN",
    "SBER_FIO_YERY_INITIAL",
    "SBER_FIO_PATRONYMIC_TOO_LONG",
    "SBER_FIO_PATRONYMIC_STEM_TOO_SHORT",
    # Size / Flate envelopes demoted — FIO/bank length and future genuines
    # shift weight; not deep structure / reassembly proof.
    "SBER_CONTENT_RAW_LENGTH_OUTLIER",
    "SBER_FILE_SIZE_STRONG_OUTLIER",
    "SBER_FONTFILE2_SIZE_STRONG_OUTLIER",
    "SBER_FONTFILE2_DEC_PROFILE",
    "SBER_GLYPH_INK_MAX_PROFILE",
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
})

# Stable profile ids used by atlas / geometry contracts.
PROFILE_IDS: frozenset[str] = frozenset({
    "sbp_outgoing",
    "sbp_request",
    "sber_internal_jasper",
    "sber_internal_pdfium",
    "legacy_phone",
    "card_other_ios",
})

# Map legacy SBR-P* codes → v2 profile ids.
LEGACY_TO_PROFILE: dict[str, str] = {
    "SBR-P1": "card_other_ios",
    "SBR-P2": "sber_internal_jasper",
    "SBR-P3": "sber_internal_pdfium",
    "SBR-P4": "legacy_phone",
    "SBR-P5": "sbp_outgoing",
    "SBR-P6": "sbp_request",
}

PROFILE_LABELS: dict[str, str] = {
    "card_other_ios": "Перевод в другой банк по номеру карты",
    "sber_internal_jasper": "Перевод клиенту СберБанка",
    "sber_internal_pdfium": "Перевод клиенту СберБанка (PDFium)",
    "legacy_phone": "Перевод по номеру телефона (legacy)",
    "sbp_outgoing": "Перевод по СБП",
    "sbp_request": "Перевод по запросу СБП",
}


def flag_code(flag: str) -> str:
    match = _CODE_RE.match(flag or "")
    return match.group(1) if match else ""


def classify_code(code: str) -> str:
    if code in KNOWN_FAKE_CODES:
        return "KNOWN"
    if code in HARD_CODES:
        return "HARD"
    if code in SUPPORTING_GROUPS:
        return "B"
    if code in IGNORED_CODES:
        return "IGNORE"
    return "IGNORE"
