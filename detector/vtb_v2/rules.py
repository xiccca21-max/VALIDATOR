"""VTB v2 rule tiers — HARD / KNOWN / Tier-B supporting groups."""

from __future__ import annotations

HARD_CODES: frozenset[str] = frozenset({
    "ANALYSIS_NOT_COMPLETED",
    "NOT_VTB_RECEIPT",
    "VTB_METHOD_SBP_TO_SELF_BANK",
    "VTB_METHOD_FIELDSET_COLLISION",
    "VTB_CARD_SENDER_RECEIVER_SAME",
    "VTB_CARD_TITLE_GRAMMAR",
    "VTB_SBP_ID_MISSING",
    "VTB_SBP_ID_STRUCTURE",
    "VTB_SBP_ID_TIMESTAMP",
    "VTB_SBP_ID_YEAR",
    "VTB_SBP_ID_0011_MISSING",
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "TRAILING_DATA_AFTER_EOF",
    "XREF_OFFSET_INVALID",
    "PDF_STRUCTURE_INVALID",
    "STREAM_DECOMPRESSION_FAILED",
    "STREAM_LENGTH_MISMATCH",
    "VTB_SBP_WIDTHS_RUNS_TOO_FEW",
    "VTB_OPENHTML_SFNT_ORDER_MISMATCH",
})

KNOWN_FAKE_CODES: frozenset[str] = frozenset({
    "VTB_KNOWN_FILE_SIGNATURE",
    "VTB_KNOWN_SEMANTIC_SIGNATURE",
    "VTB_KNOWN_ASSEMBLY_SIGNATURE",
    "VTB_SBP_LINKED_TUPLE_KNOWN_FAKE",
    "VTB_SBP_TAIL_SPLICE_KNOWN_FAKE",
    "VTB_KNOWN_FAKE_SBP_ID",
})

# Independent supporting groups (multiple flags in one group = one group).
# Method HARDs share semantic_method so they never count as two Tier-B groups.
SUPPORTING_GROUPS: dict[str, str] = {
    "VTB_SERIALIZER_CONTAINER_SHIFT": "serializer_container",
    "STREAM_COMPRESSION_RATIO_OUTLIER": "serializer_container",
    "VTB_FONT_GLYPH_SHIFT": "font_glyph",
    "VTB_SBP_EMPIRICAL_PROFILE": "sbp_grammar",
    "VTB_SBP_ID_DRIFT": "sbp_grammar",
    "VTB_CROSS_DOCUMENT_WEAK": "cross_document",
}

SUBTYPE_SBP = "vtb_sbp_outgoing"
SUBTYPE_CARD = "vtb_card_transfer"
SUBTYPE_PHONE = "vtb_internal_phone"
SUBTYPE_UNKNOWN = "vtb_unknown_coherent"

SUBTYPE_LABELS: dict[str, str] = {
    SUBTYPE_SBP: "Исходящий перевод СБП",
    SUBTYPE_CARD: "Денежный перевод / Перевод на карту",
    SUBTYPE_PHONE: "По номеру телефона клиенту ВТБ",
    SUBTYPE_UNKNOWN: "Неизвестный целостный профиль ВТБ",
}

# Versioned profile gate for method rules (disable if bank routing changes).
PROFILE_RULES_ENABLED: dict[str, frozenset[str]] = {
    "vtb_openhtml_v1": frozenset({
        "VTB_METHOD_SBP_TO_SELF_BANK",
        "VTB_METHOD_FIELDSET_COLLISION",
        "VTB_CARD_SENDER_RECEIVER_SAME",
        "VTB_CARD_TITLE_GRAMMAR",
    }),
}

VTB_BANK_ALIASES: frozenset[str] = frozenset({
    "втб",
    "банк втб",
    "банк втб пао",
    "втб пао",
    "vtb",
    "vtb bank",
})
