"""Alfa v2 rule tiers and supporting-evidence groups."""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^\[([A-Z0-9_-]+)\]")

# One HARD observation is sufficient for a fake verdict.
HARD_CODES: frozenset[str] = frozenset({
    "ANALYSIS_NOT_COMPLETED",
    "NOT_ALFA_RECEIPT",
    # Container and stream integrity.
    "PDF_STRUCTURE_INVALID",
    "MULTIPLE_PDF_HEADERS",
    "TRAILER_INVALID",
    "XREF_OFFSET_INVALID",
    "MULTIPLE_STARTXREF_PRESENT",
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
    "BROKEN_OBJECT_STRUCTURE",
    "TRAILING_DATA_AFTER_EOF",
    "OBJECT_GRAPH_INCONSISTENT",
    "STREAM_DECOMPRESSION_FAILED",
    "STREAM_LENGTH_MISMATCH",
    "UNEXPECTED_STREAM_FILTER",
    # Active content.
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "ACROFORM_PRESENT",
    "XFA_PRESENT",
    # Alfa cross-layer and provenance contradictions.
    "ALFA_PROFILE_CROSS_LAYER_CONFLICT",
    "ALFA_MIXED_SERIALIZER_PROVENANCE",
    "ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE",
    "ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH",
    "ALFA_STATIC_ASSET_PARTIAL_REPLACEMENT",
    "ALFA_STATIC_ASSET_STAMP_MISSING",
    "ALFA_FILE_SIZE_UNDERSIZE",
    # Oracle BI corpus ≤59087 (n=30). SEQ shells 59118–59796 → oversize HARD.
    "ALFA_FILE_SIZE_STRONG_OUTLIER",
    # Quartz/iOS genuines: decoded /Contents ≥5012 (n≥27). SEQ phone shells ~4786–4802.
    "ALFA_CONTENT_SIZE_STRONG_OUTLIER",
    # Quartz phone==5012 or SBP≥6004; SEQ pads midgap 5061–5065.
    "ALFA_QUARTZ_CONTENT_MIDGAP",
    # Oracle card∈{3413,4152} / SBP[5091,5542]; SEQ pads midgaps / overshoots.
    "ALFA_ORACLE_CONTENT_MIDGAP",
    # ALFA_CONTENT_DECODED_EXACT_UNKNOWN / BODY / FONTFILE2_SIZE_EXACT demoted —
    # finite corpus whitelists (n≈30); future genuines get new lengths/bodies/sizes.
    "ALFA_CLONED_ORIGINAL_SHELL_CONTENT_REWRITE",
    "ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT",
    # Semantics and linked identifiers.
    "ALFA_OPERATION_NUMBER_FORMAT",
    "ALFA_OPERATION_DATE_LINK_MISMATCH",
    "ALFA_SBP_ID_STRUCTURE_INVALID",
    "ALFA_SBP_ID_CALENDAR_CONFLICT",
    "ALFA_SBP_ID_TIME_ORDER_CONFLICT",
    "ALFA_SBP_LINKED_TUPLE_CONFLICT",
    # ALFA_SBP_ATLAS_LINK_MISMATCH demoted — incomplete link atlas / novelty
    "ALFA_FIELD_SET_METHOD_CONFLICT",
    "ALFA_AMOUNT_ARITHMETIC_MISMATCH",
    "ALFA_AMOUNT_TYPOGRAPHY_ANOMALY",
    # Amount RUR missing trailing NBSP while fee RUR keeps it (length-fit SEQ).
    "ALFA_RUR_TRAILING_NBSP_ASYMMETRY",
    "ALFA_CARD_BIN_INVALID",
    "ALFA_CARD_LAST4_ABAB",
    "ALFA_CONTENT_ET_WHITESPACE_ANOMALY",
    "ALFA_PHONE_DEF_NOT_MOBILE",
    "ALFA_MASKED_PHONE_DEF_NOT_MOBILE",
    "ALFA_PHONE_RECIPIENT_INITIALS",
    "ALFA_PHONE_NAME_UNMASKED",
    "ALFA_DEBIT_ACCOUNT_SEQUENTIAL",
    "ALFA_DEBIT_ACCOUNT_PERIODIC",
    "ALFA_DEBIT_ACCOUNT_EMPTY",
    "ALFA_OPERATION_IDENTITY_CONFLICT",
    # Font closure and rendering.
    "ALFA_USED_CID_EMPTY_GLYPH",
    "ALFA_FONT_CID_CLOSURE_VIOLATION",
    "ALFA_GLYPH_OUTLINE_MISMATCH",
    "ALFA_GLYPH_SLOT_TRANSPLANT",
    "ALFA_TEXT_GLYPH_RENDER_MISMATCH",
    "ALFA_FONTFILE2_LENGTH1_MISMATCH",
    "ALFA_FONTFILE2_SIZE_UNDERSIZE",
    "ALFA_FONT_TABLE_INTEGRITY_VIOLATION",
    "ALFA_BROKEN_UNICODE_MAPPING",
    "ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT",
    "ALFA_FONT_DESCRIPTOR_HEAD_BBOX_CONFLICT",
    "ALFA_ORACLE_SFNT_HINTING_TABLES_MISSING",
    # Used-glyph atlas conflicts + size envelopes demoted — incomplete corpus
    # / future genuine subset growth ≠ FAKE.
    # Content and visibility.
    "ALFA_CONTENT_STREAM_EDIT",
    "ALFA_OVERLAY_TEXT_LAYER",
    # Embedded FontFile2 reassembly forensics
    "ALFA_REBUILD_TTF_HEAD_EPOCH_001",
    "ALFA_REBUILD_FONT_EPOCH_PDF_TIME_CONFLICT_002",
    "ALFA_REBUILD_SUBSET_SOURCE_IDENTITY_003",
    "ALFA_REBUILD_EMITTER_FONT_LIFECYCLE_004",
    "ALFA_REBUILD_TTF_MODIFIED_VARIABILITY_005",
})

# Exact signatures are deliberately separate from structural HARD rules.
KNOWN_FAKE_CODES: frozenset[str] = frozenset({
    "ALFA-KNOWN-FAKE-001",
    "ALFA_KNOWN_FAKE_SIGNATURE",
    "ALFA_KNOWN_GENERATOR_FULL_RESERIALIZATION",
    "ALFA_KNOWN_GENERATOR_OPERATION_TIME_EMBEDDING",
    "ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION",
})

# Tier B never decides alone. Two distinct groups are required.
SUPPORTING_GROUPS: dict[str, str] = {
    # B1 — serialization/container variability.
    "STREAM_COMPRESSION_RATIO_OUTLIER": "B1_serializer_container",
    "DECODED_STREAM_SIZE_OUTLIER": "B1_serializer_container",
    "STREAM_FILTER_ANOMALY": "B1_serializer_container",
    "ALFA_SERIALIZER_PROFILE_SHIFT": "B1_serializer_container",
    "ALFA_CONTAINER_PROFILE_SHIFT": "B1_serializer_container",
    # B2 — metadata profile.
    "FOREIGN_PRODUCER": "B2_metadata_profile",
    "PDF_MODDATE_EDITED": "B2_metadata_profile",
    "ALFA_METADATA_PROFILE_SHIFT": "B2_metadata_profile",
    "ALFA_PRODUCER_PROFILE_SHIFT": "B2_metadata_profile",
    # B3 — static assets.
    "ALFA_STATIC_ASSET_PROFILE_SHIFT": "B3_static_assets",
    "ALFA_STATIC_ASSET_HASH_NEW": "B3_static_assets",
    "ALFA_IMAGE_PROFILE_SHIFT": "B3_static_assets",
    # B4 — font subsetter.
    "ALFA_FONT_SUBSETTER_PROFILE_SHIFT": "B4_font_subsetter",
    "ALFA_FONT_HASH_NEW": "B4_font_subsetter",
    "TTF_NUMGLYPHS_MISMATCH": "B4_font_subsetter",
    "TTF_HMTX_PROFILE_SHIFT": "B4_font_subsetter",
    "TTF_HEAD_ANOMALY": "B4_font_subsetter",
    # B5 — content/layout.
    "ALFA_CONTENT_LAYOUT_PROFILE_SHIFT": "B5_content_layout",
    "CONTENT_STREAM_PROFILE_MISMATCH": "B5_content_layout",
    "RIGHT_EDGE_ALIGNMENT_DRIFT": "B5_content_layout",
    "TEXT_OPERATOR_SEQUENCE_ANOMALY": "B5_content_layout",
    # B6 — empirical SBP profile.
    "ALFA_SBP_EMPIRICAL_PROFILE": "B6_sbp_empirical",
    "ALFA_SBP_TAIL_UNKNOWN": "B6_sbp_empirical",
    "ALFA_SBP_SEPARATOR_DIGIT": "B6_sbp_empirical",
    # B7 — weak cross-document correlation.
    "ALFA_CROSS_DOCUMENT_WEAK_MATCH": "B7_cross_document_weak",
    "ALFA_OPERATION_ID_WEAK_REUSE": "B7_cross_document_weak",
    "ALFA_RECEIPT_STEM_WEAK_REUSE": "B7_cross_document_weak",
}

# Observations that describe tolerated or unproven variability.
IGNORED_CODES: frozenset[str] = frozenset({
    "ALFA_PRODUCER_OBSERVATION",
    "ALFA_GENERATOR_PATH",
    "ALFA_ORACLE_ORPHANS",
    "ALFA_NEW_PROFILE",
    "ALFA_NEW_SBP_PROFILE_OBSERVED",
    "ALFA_OPERATION_ID_UNKNOWN",
    "ALFA_SBP_ATLAS_LINK_MISMATCH",
    "ALFA_USED_GLYPH_OUTLINE_ATLAS_CONFLICT",
    "ALFA_USED_GLYPH_METRIC_CONFLICT",
    "ALFA_PARTY_CONSONANT_RUN",
    "ALFA_PARTY_ALPHABET_RUN",
    "ALFA_FONTFILE2_SIZE_STRONG_OUTLIER",
    "CMAP_BFRANGE_ANOMALY",
    "TOUNICODE_PROFILE_SHIFT",
    "GLYPH_COUNT_OUTLIER",
    "FIELD_POSITION_OUT_OF_PROFILE",
    "LOCAL_ALIGNMENT_ANOMALY",
    "TTF_TRAILING_PADDING_OUTLIER",
    "BAD_UNITS_PER_EM",
    "ALFA_RENDER_STRUCTURAL_FORGERY",
    "ALFA_RENDER_FOREIGN_ROWS",
    "ALFA_CONTENT_SKELETON_UNKNOWN",
    # Exact content/font atlases = novelty on small Oracle/Quartz corpus.
    "ALFA_CONTENT_DECODED_EXACT_UNKNOWN",
    "ALFA_CONTENT_BODY_EXACT_UNKNOWN",
    "ALFA_FONTFILE2_SIZE_EXACT_UNKNOWN",
    "ALFA_LAYERED_PROFILE_FORGERY",
    "ALFA_REASSEMBLY_FORGERY",
    "ALFA_FONT_RENDER_FORGERY",
    "FF2_SUBSET_UNKNOWN",
})


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
    return "IGNORE"
