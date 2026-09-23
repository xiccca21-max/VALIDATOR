"""v6.0 rule tiers — sole T-Bank verdict source (no legacy merge)."""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^\[([A-Z0-9_-]+)\]")

# Tier A: one flag → external ФЕЙК
HARD_CODES: frozenset[str] = frozenset({
    "ANALYSIS_NOT_COMPLETED",
    "NOT_TBANK_RECEIPT",
    # Container (A-CONT-*)
    "PDF_STRUCTURE_INVALID",
    "MULTIPLE_PDF_HEADERS",
    "TRAILER_INVALID",
    "XREF_OFFSET_INVALID",
    # Catalog key order: genuine Jasper writes /Names before /Type/Catalog
    # (133/133). Reverse order is a different serializer, same dictionary.
    "TBANK_CATALOG_KEY_ORDER",
    "MULTIPLE_STARTXREF_PRESENT",
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
    "BROKEN_OBJECT_STRUCTURE",
    "TRAILING_DATA_AFTER_EOF",
    "OBJECT_GRAPH_INCONSISTENT",
    # Streams (A-STRM-*)
    "STREAM_DECOMPRESSION_FAILED",
    "STREAM_LENGTH_MISMATCH",
    "UNEXPECTED_STREAM_FILTER",
    # Active content (A-ACT-*)
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "ACROFORM_PRESENT",
    "XFA_PRESENT",
    # Content / visibility (A-VIS-*)
    "TBANK_BT_ET_MISMATCH",
    "TBANK_CONTENT_BT_TM_PROFILE",
    # TBANK_CONTENT_OPERATOR_SKELETON_UNKNOWN demoted — finite operator-skeleton
    # atlas by height (4@519, n=48); future genuine layout variants FP.
    "TBANK_CLIENT_CONTENT_SIZE_OUTLIER",
    # TBANK_FONTFILE2_SIZE_STRONG_OUTLIER demoted — envelope FP on genuine SBP
    # (finite n≠all future FF2 sizes); not competitor gate.
    "TBANK_F1_COMPOSITE_FLOOR",
    "TBANK_F1_GLYF_CMAP_OUTLIER",
    # Card-to-Sber: drawn F1 glyphs that are not on the page and not
    # composite parts. 7/7 height-471 genuines have none.
    "TBANK_F1_CARD_UNUSED_DRAWING",
    # TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN demoted — novelty exact-size atlas
    # (finite whitelist of F2 glyf lengths by MediaBox height); future genuines
    # with new Medium subsets at known heights FP. Not reassembly proof.
    # TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH demoted — known F1 hmtx kits pair
    # with new genuine Medium lengths (Receipt 15: expected 856, got 1044).
    # Height 451 midgap: only F2.glyf absent from the global genuine union
    # (SEQ phone 1130; 1144 is native Medium on other heights).
    "TBANK_F2_GLYF_HEIGHT_MIDGAP",
    # OpenPDF BaseFont subset-tag ↔ FontFile2 identity (frozen tag, foreign FF2).
    "TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH",
    # TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN / CONTENT_LEN_EXACT_UNKNOWN /
    # CMAP_CARDINALITY_UNKNOWN demoted — finite corpus whitelist FP on real
    # SBP outside atlas (incl. user orig14000/13600/5000); not reassembly proof.
    "TBANK_F1_GLYF_TRAILING_JUNK",
    # TBANK_F1_TWIN_SHAPE_MISMATCH demoted — twin shape atlas FP / not competitor
    # gate; same glyf length with different composite/simple is incomplete proof.
    # TBANK_F1_FF2_SHA_TWIN_MISMATCH demoted — one FontFile2 sha per
    # (height,cmap,glyf) is incomplete; genuines can share lengths with other bytes.
    # TBANK_CONTENT_SKELETON_EXACT_UNKNOWN demoted — finite corpus whitelist;
    # future genuines can have new layout skeletons at same height.
    "TBANK_CONTENT_STREAM_EDIT",
    "TEXT_LAYER_INCONSISTENT",
    "BROKEN_CYRILLIC_MAPPING",
    "TEXT_EXTRACTION_MAPPING_ANOMALY",
    "UNICODE_MAPPING_INVALID",
    "OVERLAY_DETECTED",
    "OVERLAY_TEXT_LAYER",
    "RECEIPT_TEXT_LAYER_MISSING",
    # Fonts (A-FONT-*)
    "USED_CID_MISSING_FROM_CMAP",
    "USED_CID_MISSING_FROM_W",
    "USED_CID_CMAP_MISMATCH",
    "CMAP_W_MISMATCH",
    "CMAP_INVALID",
    "FONTFILE2_CID_MISSING",
    "FONTFILE2_MISSING",
    "MISSING_FONT_OBJECT",
    "MISSING_WIDTH_TABLE",
    "W_ARRAY_PRETTY_PRINTED",
    "W_ARRAY_SERIALIZATION_ANOMALY",
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH",
    "BROKEN_GLYPH_ZERO_LENGTH",
    "USED_CID_EMPTY_GLYPH",
    "GLYPH_SLOT_TRANSPLANT",
    "TBANK_TEXT_GLYPH_PARITY",
    "GLYPH_BBOX_IMPOSSIBLE",
    "LOCA_TABLE_BROKEN",
    "GLYPH_OUTLINE_MISMATCH",
    "F3_NOT_ALSRUBL",
    "TBANK_RUBLE_GLYPH_SPACING",
    # TBANK_GLYPH_INK_OVERLAP demoted — competitor-accepted card/SBP SEQ can
    # show local ink overlap; not their gate and not 0-FP vs future genuines.
    # Semantics (A-SEM-*)
    "SBP_CIPHER_MISSING",
    "SBP_CIPHER_STRUCTURE",
    "SBP_CIPHER_TIMESTAMP",
    "SBP_CIPHER_REFERENCE",
    "SBP_REFERENCE_NON_NUMERIC",
    "SBP_PROFILE_EPOCH_EXPIRED",
    "SBP_PROFILE_EPOCH_SLOT_CONFLICT",
    "SBP_PROFILE_EPOCH_SUFFIX_CONFLICT",
    "SBP_PROFILE_SUFFIX_OWNER_CONFLICT",
    "SBP_ROUTE_FIELD_CONTAMINATION",
    "SBP_CONTROL_TRIPLE_MISMATCH",
    "SBP_LINKED_TUPLE_CROSS_CLASS",
    "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT",
    "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH",
    "TBANK_FONT_GLYF_TRAILING_DATA",
    "TBANK_SBP_TUPLE_GLYF_RESIDUE_SIGNATURE",
    "TBANK_COMPETITOR_NOVELTY_COMBO_001",
    "TBANK_COMPETITOR_TUPLE_791103_COMBO_002",
    "TBANK_COMPETITOR_TUPLE_017_791103_COMBO_003",
    "TBANK_COMPETITOR_TUPLE_018_NATIVE_COMBO_004",
    "SBP_PROFILE_EPOCH_TOO_EARLY",
    "TBANK_DEBIT_ACCOUNT_PREFIX",
    # SBP_GRAMMAR_SUFFIX_PROFILE demoted — incomplete suffix atlas / novelty
    # TBANK_SBP_GEOMETRY_MISMATCH demoted — R≈250 SBP-column noise; fires on
    # genuine phone/SBP donors when shortfall/overflow is parser slack, not forgery.
    "TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH",
    "FIELD_FORMAT_INVALID",
    "STRING_FIELD_STRUCTURE_ANOMALY",
    "FIELD_ORDER_MISMATCH",
    "FIELD_SET_MISMATCH",
    "MISSING_REQUIRED_FIELD_BLOCK",
    "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS",
    "OPERATION_ID_REUSED",
    # Known signatures (A-SIG-*)
    "TBANK_KNOWN_GENERATOR_SKELETON",
    "TBANK_KEYWORDS_GENERATION_MISMATCH",
    "TBANK_INFO_KEYWORDS_LEX_MISMATCH",
    "MIXED_FLATE_SERIALIZER_PROVENANCE",
    "TBANK_DEFLATE_PROFILE_MISMATCH",
    "TBANK_FONT_CID_CLOSURE_VIOLATION",
    "TBANK_RECEIPT_NUMBER_FORMAT",
    "TBANK_STREAM_INTEGRITY_VIOLATION",
    "TBANK_FONT_TABLE_INTEGRITY_VIOLATION",
    "TBANK_FOREIGN_PRODUCER",
    "FOREIGN_PRODUCER",
    "TTF_CHECKSUM_ADJUSTMENT_INVALID",
    "TTF_HMTX_COUNT_MISMATCH",
    "W_MISSING_CID",
    # Exact subset minimality / bijection / closure (family v3 stack)
    "TBANK_SUBSET_CMAP_NOT_MINIMAL",
    "TBANK_W_ARRAY_NOT_MINIMAL",
    "TBANK_W_TTF_ADVANCE_MISMATCH",
    "TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION",
    "TBANK_FONT_SUBSET_EXACT_CLOSURE",
    # Unmapped nonempty FontFile2 residue (F2 pad ≥2 or F1 kit pair 113+227)
    "TBANK_FONT_SUBSET_ORPHAN_RESIDUE",
    # Jasper keeps full-font maxp; SEQ recomputes extrema to subset glyf
    "TBANK_F1_MAXP_RECOMPUTED_TO_SUBSET",
    "TBANK_F1_MAXP_COMPOSITE_ENVELOPE_MISMATCH",
    "TBANK_F1_HHEA_ENVELOPE_MISMATCH",
    # Jasper Medium keeps full-font F2 head; SEQ rewrites checkSumAdjustment
    "TBANK_F2_HEAD_ENVELOPE_MISMATCH",
    "TBANK_F2_MAXP_ENVELOPE_MISMATCH",
    "TBANK_F1_HMTX_ENVELOPE_MISMATCH",
    "TBANK_F2_GLYF_LOCA_PADDING",
    "TBANK_F2_GLYF_DIGIT_CARD_FAT",
    # TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH / SIZE_MULTISET demoted — finite
    # glyf_len atlas FP on genuines (Receipt 15 shape; новые чеки 12784 size).
    # Jasper/OpenPDF emitter invariants (serializer + FontFile2 laws)
    "TBANK_SFNT_TABLE_ORDER_MISMATCH",
    "TBANK_GLYF_ZERO_CONTOUR_STUB",
    "TBANK_LOCA_ODD_OFFSET",
    "TBANK_HMTX_METRIC_CARDINALITY",
    "TBANK_COMPOSITE_EMPTY_COMPONENT",
    "TBANK_TOUNICODE_BFCHAR_PRESENT",
    "TBANK_FORBIDDEN_FONT_DESCRIPTOR_KEY",
    "TBANK_PROCSET_PRESENT",
    "TBANK_FLATE_PREDICTOR_PRESENT",
    "TBANK_STREAM_CRLF_EOL",
    "TBANK_CONTENT_TJ_PRESENT",
    "TBANK_MARKED_CONTENT_PRESENT",
    "TBANK_BT_NESTING_VIOLATION",
    # F1 SFNT table inventory (native Jasper/OpenPDF subset)
    "TBANK_TTF_UNEXPECTED_SFNT_TABLE",
    "TBANK_TTF_REQUIRED_SFNT_TABLE_MISSING",
    "TBANK_TTF_INERT_PADDING_TABLE",
    # F2 .notdef / cross-font notdef asymmetry / Итого amount serialization
    "TBANK_F2_NOTDEF_GLYPH_EMPTY",
    "TBANK_F2_NOTDEF_NATIVE_PROFILE_MISMATCH",
    "TBANK_FONT_NOTDEF_ASYMMETRY",
    "TBANK_AMOUNT_TEXT_SERIALIZATION_MISMATCH",
    # TBANK_F1_ORPHAN_SIMPLE_GLYPH demoted — fires on competitor-PASS SBP that
    # already match exact glyf twin + clean loca; orphan alone ≠ their signal.
    # TBANK_F1/F2_HEAD_MODIFIED_EPOCH demoted — competitor-PASS card SEQ;
    # frozen modified epoch is incomplete vs bank font revisions.
    # CARD_OTHER content-stream whitespace padding family
    "TBANK_CARD_OTHER_INTERNAL_WHITESPACE_PADDING",
    # Jasper never emits Tm with ≥3 fractional digits — reassembly/edit artifact
    "FIELD_POSITION_OUT_OF_PROFILE",
    "TM_NOT_RECALCULATED",
    "TBANK_GLYPH_MOSAIC_HASH_MISMATCH",
    # TBANK_GLYPH_MOSAIC_INCOMPLETE / size / skeleton / BT·Tm pins demoted —
    # incomplete corpus ≠ FAKE. Keep structural emitter invariants only.
    "TBANK_CONTENT_CID_SEQUENCE_ANOMALY",
    "TBANK_CONTENT_ET_WHITESPACE_ANOMALY",
    "TBANK_CONTENT_INDENTED_OPERAND",
    "TBANK_CONTENT_TJ_TRAILING_WHITESPACE",
    "TBANK_CONTENT_FLOAT_TRAILING_ZERO",
    "TBANK_CONTENT_TD_RUN_ANOMALY",
    "TBANK_CONTENT_TD_TJ_INTERLEAVE",
    "TBANK_CONTENT_TD_SENTINEL",
    "TBANK_CONTENT_IMG_TD_SCALE_MISMATCH",
    "TBANK_CONTENT_TR_MODE_ANOMALY",
    "TBANK_AMOUNT_LEADING_ZERO",
    "TBANK_SENDER_LEADING_WHITESPACE",
    "TBANK_RECIPIENT_LEADING_WHITESPACE",
    "TBANK_TEXT_TRAILING_WHITESPACE",
    "TEXT_TRAILING_NBSP_PADDING",
    "TBANK_AMOUNT_LEADING_WHITESPACE",
    # Channel text on a *known foreign* shell height (unknown heights skip).
    "TBANK_CHANNEL_MEDIABOX_MISMATCH",
    # Receipt «№ N-NNN-…» with trailing CID garbage (NUL/dagger/combining).
    "TBANK_RECEIPT_ID_TRAILING_JUNK",
    # Phone / SBP recipient must be mobile DEF 9xx when phone field present.
    "TBANK_PHONE_DEF_NOT_MOBILE",
    "TBANK_PHONE_SUBSCRIBER_UNIFORM",
    "TBANK_CARD_MASK_NULL_TEMPLATE",
    "TBANK_DATETIME_ZERO_SECONDS",
    # Support contact line spacing / exact grammar.
    "TBANK_SUPPORT_CONTACT_SPACING",
    # Missing/garbled «Служба поддержки fb@tbank.ru» (SEQ ToUnicode strip).
    "TBANK_SUPPORT_CONTACT_CORRUPTED",
    # Static field label mojibake (e.g. «þелефон получателя» / «Перевiд»).
    "TBANK_STATIC_LABEL_CORRUPTED",
    # First text line is always DD.MM.YYYY on Jasper IB/Receipt (n=133).
    "TBANK_DATE_LINE_CORRUPTED",
    # OpenPDF: unused CMap leftovers (template glyphs not in text).
    "UNUSED_CID_PRESENT",
    "CMAP_EXTRA_SYMBOLS",
    # Value-column right edges must share one vertical (relative spread only).
    "TBANK_VALUE_RIGHT_EDGE_SPREAD",
    # Value-column past R=250 (footer amount/₽ SEQ drift) / card residual lattice.
    "TBANK_VALUE_RIGHT_EDGE_OVERSHOOT",
    "TBANK_VALUE_RIGHT_EDGE_OFF_LATTICE",
})

KNOWN_FAKE_CODES: frozenset[str] = frozenset({
    "K-FONT-001",
    # K-FONT-002 disabled — glyf/loca hash cloning / novelty
    "KNOWN_FAKE_SBP_GRAMMAR_COMBINATION",
    "TBANK_REASSEMBLED_BANK_ASSETS",
    "TBANK_REASSEMBLED_BANK_ASSETS_V2",
    # Embedded FontFile2 reassembly forensics
    "TBANK_REBUILD_FONT_DUAL_DYNAMIC_001",
    "TBANK_REBUILD_STATIC_F3_DYNAMIC_F12_SPLIT_002",
    "TBANK_REBUILD_GLYPH_PAYLOAD_WITH_FROZEN_HEAD_003",
    "TBANK_REBUILD_F1_F2_COGENERATION_004",
    "TBANK_REBUILD_CANONICAL_SHELL_FOREIGN_SUBSETTER_005",
    # F1/F2 reconstructed-subset serialization family v3
    "TBANK_REASSEMBLY_FAMILY_V3",
    # Confirmed serializer families (DOCS-2035 + structural conjunctions)
    "TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1",
    "TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1",
    "TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1",
})

# Tier B: external ФЕЙК only when ≥2 independent groups agree
SUPPORTING_GROUPS: dict[str, str] = {
    "PDF_MODDATE_EDITED": "B6_metadata_version",
    "TBANK_SHELL_PRODUCER_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_CREATOR_MISMATCH": "B6_metadata_version",
    "TBANK_SHELL_SUBJECT_MISMATCH": "B6_metadata_version",
    "STREAM_COMPRESSION_RATIO_OUTLIER": "B1_serializer_container",
    "DECODED_STREAM_SIZE_OUTLIER": "B1_serializer_container",
    "STREAM_FILTER_ANOMALY": "B1_serializer_container",
    "TTF_NUMGLYPHS_MISMATCH": "B5_source_fonts",
    "TTF_HEAD_ANOMALY": "B5_source_fonts",
    "TTF_HMTX_PROFILE_SHIFT": "B5_source_fonts",
    # UNUSED_CID_PRESENT / CMAP_EXTRA_SYMBOLS promoted to HARD for OpenPDF
    "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER": "B5_font_rebuilder",
    "STATIC_EDITABLE_DIGIT_SUBSET_F2": "B5_font_rebuilder",
    "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE": "B5_font_rebuilder",
    "EXTRA_UNUSED_GLYPHS_F1_F2": "B5_font_rebuilder",
    "TBANK_TEXT_LAYOUT_FINGERPRINT": "content_grammar_layout",
    "SBP_TBANK_BANK5_MISMATCH": "content_grammar_sbp",
    "SBP_PROFILE_EMPIRICAL": "content_grammar_sbp",
    "SBP_PROFILE_EPOCH_MISMATCH": "content_grammar_sbp_epoch",
    "RECEIPT_STEM_REUSE_CONFLICT": "cross_document_receipt_stem",
}

# DELETED / IGNORE — must not affect verdict
IGNORED_CODES: frozenset[str] = frozenset({
    # Observed on confirmed genuine receipts: corpus tuples and trailer /ID
    # reuse are diagnostic provenance observations, not forgery proof.
    "SBP_LINKED_TUPLE_CONFLICT",
    "TBANK_TRAILER_ID_REUSED",
    # Novelty / incomplete corpus — never FAKE alone (future genuine variants).
    "TBANK_GLYPH_MOSAIC_INCOMPLETE",
    "TBANK_CONTENT_SIZE_STRONG_OUTLIER",
    "TBANK_FILE_SIZE_STRONG_OUTLIER",
    "TBANK_PARTY_NAME_CONSONANT_RUN",
    "TBANK_PARTY_NAME_ALPHABET_RUN",
    "SBP_GRAMMAR_SUFFIX_PROFILE",
    "TBANK_RENDER_STRUCTURAL_FORGERY",
    "TBANK_FONT_RENDER_FORGERY",
    "TBANK_RENDER_FOREIGN_ROWS",
    "TBANK_CHANNEL_SKELETON_UNKNOWN",
    "TBANK_CONTENT_SKELETON_UNKNOWN",
    # Exact structure-skeleton atlas = novelty (n=24…110 ≠ all future genuines).
    "TBANK_CONTENT_SKELETON_EXACT_UNKNOWN",
    # Operator-only skeleton atlas by MediaBox height — same novelty class.
    "TBANK_CONTENT_OPERATOR_SKELETON_UNKNOWN",
    # F2 Medium glyf×height exact whitelist — same novelty class as F1 exact.
    "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN",
    "TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN",
    "TBANK_SBP_F1_GLYF_CMAP_UNKNOWN",
    "TBANK_CONTENT_LEN_EXACT_UNKNOWN",
    "TBANK_F1_CMAP_CARDINALITY_UNKNOWN",
    "TBANK_F1_TWIN_SHAPE_MISMATCH",
    "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH",
    # Finite glyf_len → glyph-size-multiset atlas; genuines share length with
    # a different outline set (новые чеки F1.glyf=12784).
    "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH",
    # Ascending last4 (3456/4567) occurs on real «На карту» cards.
    "TBANK_CARD_LAST4_SEQUENTIAL",
    "TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH",
    # Same (h,cmap,glyf) can map to multiple genuine FontFile2 digests; atlas
    # often has allowed_n=1 → FP on real twins outside the recorded sha.
    "TBANK_F1_FF2_SHA_TWIN_MISMATCH",
    "TBANK_F1_ORPHAN_SIMPLE_GLYPH",
    "TBANK_GLYPH_INK_OVERLAP",
    "TBANK_FONTFILE2_SIZE_STRONG_OUTLIER",
    "TBANK_F1_HEAD_MODIFIED_EPOCH",
    "TBANK_F2_HEAD_MODIFIED_EPOCH",
    "TBANK_REASSEMBLY_FORGERY",
    "TBANK_LAYERED_PROFILE_FORGERY",
    "FF2_SUBSET_UNKNOWN",
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
    "TBANK_COORDINATE_DRIFT",
    "TBANK_RIGHT_EDGE_DRIFT",
    "TBANK_BASELINE_DRIFT",
    # SBP ID right-edge vs R≈250: parser/rounding noise on genuines (incl. phone
    # donors); keep as diagnostic only.
    "TBANK_SBP_GEOMETRY_MISMATCH",
    "TBANK_OPERATOR_FINGERPRINT",
    "TBANK_STREAM_ZLIB_HEADER",
    "TBANK_SHELL_PAGE_HEIGHT",
    "TBANK_SHELL_EOF_COUNT",
    "TBANK_SHELL_XREF_COUNT",
    "TBANK_F3_HASH_MISMATCH",
    "TBANK_F3_SIZE_MISMATCH",
    "TBANK_F3_NUMGLYPHS",
    "CMAP_BFRANGE_ANOMALY",
    "TOUNICODE_PROFILE_SHIFT",
    "CONTENT_STREAM_PROFILE_MISMATCH",
    "RIGHT_EDGE_ALIGNMENT_DRIFT",
    "GLYPH_COUNT_OUTLIER",
    "TEXT_OPERATOR_SEQUENCE_ANOMALY",
    "PROFILE_CLUSTER_OUTLIER",
    "FONT_AUTH_FOREIGN_FONT",
})

# Forensics HIGH codes that stay stats-only in v6 (supporting/ignore)
_FORENSICS_STATS_ONLY: frozenset[str] = frozenset({
    "CMAP_BFRANGE_ANOMALY",
    "TOUNICODE_PROFILE_SHIFT",
    "GLYPH_COUNT_OUTLIER",
    "TTF_HMTX_PROFILE_SHIFT",
    "TTF_HEAD_ANOMALY",
    "TTF_TRAILING_PADDING_OUTLIER",
    "BAD_UNITS_PER_EM",
    "RIGHT_EDGE_ALIGNMENT_DRIFT",
    "LOCAL_ALIGNMENT_ANOMALY",
    "CONTENT_STREAM_PROFILE_MISMATCH",
    "TEXT_OPERATOR_SEQUENCE_ANOMALY",
    "UNEXPECTED_TEXT_BLOCK_STRUCTURE",
    "W_EXTRA_CID",
    "MISSING_CMAP_OBJECT",
})

KNOWN_GENERATOR_SKELETONS: frozenset[str] = frozenset({
    "104eb3a947e4bc40",
    "bc1d467eabb5bfae",
    "220bf37ae2f7fa3c",
    "e4733e1c6cbe27b0",
    "8afaff6d932067fa",
    "293b41b126bde1bc",
})

K_FONT_002_GLYF_SHA = (
    "e3bfdef68a1a74118a7a1b17b86c57d60d9915e6a2ea33a0e59284dfc47c806c"
)
K_FONT_002_LOCA_SHA = (
    "1d0acb894775526e8a5045e6db696ee2d800b8dac1c2bf4b7b70cef35a153175"
)

# Exact F2 glyf/loca packs from generator slips.
# CRITICAL: every pack must have 0 hits on чеки/** genuines (validated 2026-07-31).
# Earlier expansion polluted with real TinkoffSans-Medium subsets → K-FONT-002 FP
# (e.g. mail DKIM-ok Receipt.pdf with glyf 7b6a8337… / loca 40cd585c…).
K_FONT_002_PACKS: frozenset[tuple[str, str]] = frozenset({
    (K_FONT_002_GLYF_SHA, K_FONT_002_LOCA_SHA),
    (
        "30e91115966e3b4bff459c13c051617601280e200a5cd830a6f594a3901c3daa",
        "15e7ce33ca7e8fe7acd3a05269732bb8265478c9cf89dfec729289e033ea53a4",
    ),
    (
        "f6d8d1c6baf7f091eed3d9dcdb4e6fffb79c0f296e07de9e7bdd2965a4135ae8",
        "3e2d8aaea199a19813f77b53774189384e12df64a82dbb936e79680eabd6dbaf",
    ),
    (
        "62b767ba84869327c29ceba218e916774d81989c061c488e8e07dc0b3313ff5e",
        "2660aefba87d8ac0b4302220576841225536155a84fcf25e0018882c3db5348f",
    ),
})


def flag_code(flag: str) -> str:
    m = _CODE_RE.match(flag or "")
    return m.group(1) if m else ""


def classify_code(code: str) -> str:
    if code in KNOWN_FAKE_CODES:
        return "KNOWN"
    if code in HARD_CODES:
        return "A"
    if code in IGNORED_CODES:
        return "IGNORE"
    if code in SUPPORTING_GROUPS:
        return "B"
    if code in _FORENSICS_STATS_ONLY:
        return "IGNORE"
    return "IGNORE"
