"""
Вердикт: подделка или нет.

Формула chadgpt-plus (Т-Банк):
  FAKE если: shell | producer | active_content | missing_fonts | broken_cid |
             broken_glyph | broken_font_tables | overlay | amount | layout

Не баним по: одиночный F1 SHA, rare_letters, file_size, «новый ToUnicode».
Статистические дрейфы вне корпуса — не считаем фейком.
"""

from __future__ import annotations

import re

from .corpus_signals import is_corpus_stat_code
from .policy_v5 import aggregate_policy, classify_flag

FAKE_THRESHOLD = 60

# Жёсткие коды по формуле chadgpt-plus + проверенные T-Bank сигналы
_FORGERY_CODES = frozenset({
    # §1 PDF shell
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "MULTIPLE_PDF_HEADERS",
    "MULTIPLE_STARTXREF_PRESENT",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
    "XREF_OFFSET_INVALID",
    "PDF_STRUCTURE_INVALID",
    "TRAILER_INVALID",
    "BROKEN_OBJECT_STRUCTURE",
    "STREAM_DECOMPRESSION_FAILED",
    "OBJECT_GRAPH_INCONSISTENT",
    # §2 Foreign producer
    "FOREIGN_PRODUCER",
    "RAIF_CONTENT_CID_ZERO",
    # §3 Active content
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "ACROFORM_PRESENT",
    "XFA_PRESENT",
    "TRAILING_DATA_AFTER_EOF",
    # §4 Fonts / Alfa Oracle BI
    "ALFA_PRODUCER_MISMATCH",
    "ALFA_MISSING_TAHOMA",
    "ALFA_JASPER_CLONE",
    "ALFA_CONTENT_STREAM_MISSING",
    "ALFA_CONTENT_STREAM_OUTLIER",
    "ALFA_CONTENT_PREFIX_MISMATCH",
    "ALFA_TEXT_COLOR_MISMATCH",
    "ALFA_CONTENT_STREAM_TAIL_PADDING",
    "ALFA_IMAGE_LAYOUT_MISMATCH",
    "ALFA_OBJECT_COUNT_OUTLIER",
    "ALFA_FONTFILE2_COUNT_OUTLIER",
    "ALFA_FONTFILE2_SIZE_OUTLIER",
    "ALFA_FONTFILE2_NAME_MISMATCH",
    "ALFA_AMOUNT_MISSING",
    "ALFA_SBP_ID_MISSING",
    "ALFA_SBP_ID_STRUCTURE",
    "ALFA_SBP_ID_TIMESTAMP",
    "ALFA_SBP_ID_REFERENCE",
    "ALFA_BANK_OP_ID_STRUCTURE",
    "ALFA_OPERATION_ID_MISMATCH",
    "SBP_CIPHER_MISSING",
    "SBP_CIPHER_STRUCTURE",
    "SBP_CIPHER_TIMESTAMP",
    "SBP_CIPHER_REFERENCE",
    "SBER_SBP_OPID_INVALID",
    "SBER_OPERATION_AFTER_PDF_CREATION",
    "SBER_DYNAMIC_NOW_IN_STATIC_RECEIPT",
    "SBER_TEXT_LAYER_CORRUPT",
    "SBER_AMOUNT_GLYPH_CORRUPT",
    "SBER_AMOUNT_FORMAT_ANOMALY",
    "YANDEX_CREATION_TIME_MISMATCH",
    "YANDEX_CREATION_DATE_FORMAT",
    "YANDEX_YSTEXT_FULLFONT_METRICS",
    "YANDEX_KNOWN_FILE_SIGNATURE",
    "RECEIPT_TEXT_LAYER_MISSING",
    "PDF_MODDATE_EDITED",
    "OPERATION_ID_REUSED",
    "TBANK_RUBLE_GLYPH_SPACING",
    "TBANK_CONTENT_STREAM_EDIT",
    "TBANK_SHELL_PRODUCER_MISMATCH",
    "TBANK_SHELL_CREATOR_MISMATCH",
    "TBANK_SHELL_SUBJECT_MISMATCH",
    "TBANK_SHELL_PAGE_WIDTH",
    "TBANK_SHELL_EOF_COUNT",
    "TBANK_SHELL_PREV_PRESENT",
    "TBANK_F3_HASH_MISMATCH",
    "TBANK_F3_SIZE_MISMATCH",
    "TBANK_F3_NUMGLYPHS",
    "TBANK_BT_ET_MISMATCH",
    "TBANK_KNOWN_GENERATOR_SKELETON",
    "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE",
    "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH",
    "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER",
    "STATIC_EDITABLE_DIGIT_SUBSET_F2",
    "TBANK_SBP_STREAM_FIELD_ORDER",
    "FIELD_FORMAT_INVALID",
    "STRING_FIELD_STRUCTURE_ANOMALY",
    "FIELD_ORDER_MISMATCH",
    "FIELD_SET_MISMATCH",
    "MISSING_REQUIRED_FIELD_BLOCK",
    "BANK_PRODUCER_MISMATCH",
    "BANK_PRODUCER_VERSION_MISMATCH",
    "BANK_FONT_MISSING",
    "BANK_FONTFILE2_COUNT_OUTLIER",
    "BANK_FONTFILE2_SIZE_OUTLIER",
    "BANK_FONTFILE2_NAME_MISMATCH",
    "BANK_JASPER_CLONE",
    "BANK_CONTENT_STREAM_MISSING",
    "MISSING_REQUIRED_FONT",
    "MISSING_FONT_OBJECT",
    "F3_NOT_ALSRUBL",
    "FONTFILE2_MISSING",
    # §5 CID
    "USED_CID_MISSING_FROM_CMAP",
    "USED_CID_MISSING_FROM_W",
    "USED_CID_CMAP_MISMATCH",
    "CMAP_W_MISMATCH",
    "CMAP_INVALID",
    "FONTFILE2_CID_MISSING",
    "UNICODE_MAPPING_INVALID",
    # §6 Glyph
    "BROKEN_GLYPH_ZERO_LENGTH",
    "GLYPH_BBOX_IMPOSSIBLE",
    "LOCA_TABLE_BROKEN",
    "GLYPH_OUTLINE_MISMATCH",
    # §7 Font tables
    "TTF_NUMGLYPHS_MISMATCH",
    "TTF_HMTX_COUNT_MISMATCH",
    "TTF_HMTX_PROFILE_SHIFT",
    "UNUSED_CID_PRESENT",
    "CMAP_EXTRA_SYMBOLS",
    "TTF_CHECKSUM_ADJUSTMENT_INVALID",
    "TTF_HEAD_ANOMALY",
    # §8 Overlay
    "OVERLAY_DETECTED",
    "OVERLAY_TEXT_LAYER",
    "TEXT_LAYER_INCONSISTENT",
    "TEXT_EXTRACTION_MAPPING_ANOMALY",
    "BROKEN_CYRILLIC_MAPPING",
    # §9 Amounts
    "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS",
    # §10 Layout
    "LAYOUT_FAMILY_VIOLATION",
    "LAYOUT_FAMILY_MISSING",
    # W / reserialization (редактор PDF)
    "W_ARRAY_PRETTY_PRINTED",
    "W_ARRAY_SERIALIZATION_ANOMALY",
    # Контур глифа внутри слова (структурный, не корпусный whitelist)
    "TOTAL_LABEL_SPLIT_BETWEEN_FONTS",
    "FONT_SWITCH_INSIDE_WORD",
    "ANALYSIS_NOT_COMPLETED",
})

# Prefixes reserved for future invariant glyph checks (corpus glyf → stats_only).
_FORGERY_PREFIXES: tuple[str, ...] = ()

_FORGERY_PHRASES = (
    "подозрительный producer",
    "сторонний инструмент pdf",
    "пересобран",
    "перепакован",
    "pikepdf", "ilovepdf", "pypdf", "reportlab", "acrobat", "itext",
    "pdf-lib", "libreoffice", "canva",
    "целостность pdf нарушена",
    "текстовый content stream не найден",
    "producer «",
    "инкрементальное обновление",
    "маркеров %%eof",
    "таблиц xref",
    "/prev",
    "отмечен пользователями как фейк",
    "чёрный список",
    "sbp_opid",
    "keywords",
    "broken_glyphmap",
    "foreign_width",
    "creation_eq",
    "id_hex_case",
    "tinkoffsans встроен полностью",
    "шаблонный номер квитанции",
    "javascript",
    "опасн",
    "openaction",
    "acroform",
    "вложенн",
)

# Явно НЕ forgery (запрет из спецификации + статистика)
_NON_FORGERY_CODES = frozenset({
    # Profile/corpus drift: useful for analyst logs, but a new genuine bank
    # template can legitimately move outside our current corpus.
    "ALFA_PRODUCER_MISMATCH",
    "ALFA_MISSING_TAHOMA",
    "ALFA_CONTENT_STREAM_OUTLIER",
    "ALFA_CONTENT_PREFIX_MISMATCH",
    "ALFA_TEXT_COLOR_MISMATCH",
    "ALFA_IMAGE_LAYOUT_MISMATCH",
    "ALFA_OBJECT_COUNT_OUTLIER",
    "ALFA_FONTFILE2_COUNT_OUTLIER",
    "ALFA_FONTFILE2_SIZE_OUTLIER",
    "ALFA_FONTFILE2_NAME_MISMATCH",
    "BANK_PRODUCER_MISMATCH",
    "BANK_FONT_MISSING",
    "BANK_FONTFILE2_COUNT_OUTLIER",
    "BANK_FONTFILE2_SIZE_OUTLIER",
    "BANK_FONTFILE2_NAME_MISMATCH",
    "BANK_OBJECT_COUNT_OUTLIER",
    "BANK_CONTENT_STREAM_MISSING",
    "BANK_CONTENT_STREAM_OUTLIER",
    "BANK_CONTENT_SKELETON_UNKNOWN",
    "BANK_FILE_SIZE_OUTLIER",
    "TBANK_COORDINATE_DRIFT",
    "TBANK_RIGHT_EDGE_DRIFT",
    "TBANK_BASELINE_DRIFT",
    "TBANK_OPERATOR_FINGERPRINT",
    "TBANK_STREAM_ZLIB_HEADER",
    "TBANK_F1_HMTX_DRIFT",
    "TBANK_F2_HMTX_DRIFT",
    "TBANK_F1_HEAD_DRIFT",
    "TBANK_F2_HEAD_DRIFT",
    "TBANK_F1_MAXP_DRIFT",
    "TBANK_F2_MAXP_DRIFT",
    "TBANK_F1_W_ARRAY_UNKNOWN",
    "TBANK_F2_W_ARRAY_UNKNOWN",
    "TBANK_F1_TOUNICODE_COUNTS",
    "TBANK_F2_TOUNICODE_COUNTS",
    "FF2_SUBSET_UNKNOWN",
    "FONT_AUTH_FOREIGN_FONT",
    "TBANK_LAYERED_PROFILE_FORGERY",
    "TBANK_REASSEMBLY_FORGERY",
    "TBANK_CHANNEL_SKELETON_UNKNOWN",
    "TBANK_FONT_RENDER_FORGERY",
    "TBANK_RENDER_STRUCTURAL_FORGERY",
    "TBANK_CONTENT_SKELETON_UNKNOWN",
    "TBANK_TEMPLATE_HEIGHT_UNKNOWN",
    "TBANK_TEMPLATE_HEIGHT_MISMATCH",
    "TBANK_TEMPLATE_STREAM_SIZE",
    "TBANK_TEMPLATE_OPERATOR_COUNT",
    "TBANK_TEMPLATE_LABEL_DRIFT",
    "TBANK_F1_NUMGLYPHS",
    "TBANK_F2_NUMGLYPHS",
    "TBANK_SHELL_PAGE_HEIGHT",
    "TBANK_SHELL_XREF_COUNT",
    "GLYPH_COUNT_OUTLIER",
    "TTF_HMTX_PROFILE_SHIFT",
    "SBER_SBP_OPERATOR_DRIFT",
    "SBER_SBP_LAYOUT_DRIFT",
    "SBER_SBP_LAYOUT_MISSING_FIELDS",
    "SBER_SBP_LAYOUT_PARSE_FAILED",
    "CMAP_BFRANGE_ANOMALY",
    "TOUNICODE_PROFILE_SHIFT",
    "BFCHAR_IN_TOUNICODE",
    "CONTENT_STREAM_PROFILE_MISMATCH",
    "FONTFILE2_SIZE_OUTLIER",
    "FONT_AUTH_NAME_DRIFT",
    "FONT_AUTH_TABLE_DRIFT",
    "RIGHT_EDGE_ALIGNMENT_DRIFT",
    "FIELD_POSITION_OUT_OF_PROFILE",
    "F1_CID_CLUSTER_NOT_OBSERVED",
    "PROFILE_CLUSTER_OUTLIER",
    "MULTIPLE_WEAK_ANOMALIES",
})

_NON_FORGERY_PREFIXES = (
    "CLUSTER_",
    "NOT_OBSERVED",
    "COMPACT_SUBSET",
    "PARSE_FAILED",
    "SYMBOL_",
    "GLYPH_TTF_",
    "GLYPH_PIX_",
    "TBANK_TEMPLATE_",
)

_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]")


def is_forgery_flag(flag: str) -> bool:
    """True если флаг — признак подделки, а не статистический шум."""
    fl = (flag or "").lower()
    m = _CODE_RE.match(flag or "")
    if m:
        code = m.group(1)
        if code in _NON_FORGERY_CODES:
            return False
        if is_corpus_stat_code(code):
            return False
        if any(code.startswith(p) for p in _NON_FORGERY_PREFIXES):
            return False
        if code in _FORGERY_CODES:
            return True
        if any(code.startswith(p) for p in _FORGERY_PREFIXES):
            return True
        if any(x in code for x in (
            "CLUSTER_DRIFT", "CLUSTER_OUTLIER", "WEAK_ANOMALIES",
            "PROFILE_MISMATCH", "ALIGNMENT_DRIFT", "OUT_OF_PROFILE",
            "NOT_OBSERVED", "COMPACT_SUBSET",
        )):
            return False
    return any(p in fl for p in _FORGERY_PHRASES)


def split_flags(flags: list[str]) -> tuple[list[str], list[str]]:
    forgery = [f for f in flags if is_forgery_flag(f)]
    other = [f for f in flags if f not in forgery]
    return forgery, other


def finalize_verdict(score: int, flags: list[str]) -> tuple[str, str, int, list[str]]:
    """
    v5.2 binary policy:
    - Tier A: hard FAKE.
    - Two independent Tier B groups: FAKE.
    - One Tier B group or Tier C/statistical drift: diagnostics only.
    External verdict is binary: ЧИСТО/ФЕЙК.
    """
    policy = aggregate_policy(flags)
    if policy["verdict"] == "ФЕЙК":
        evidence = policy["tier_a_flags"] or policy["tier_b_flags"]
        effective = forgery_score_from_flags(evidence) if evidence else FAKE_THRESHOLD
        return "ФЕЙК", "🔴", max(effective, FAKE_THRESHOLD), evidence

    policy_codes = {classify_flag(f).code for f in flags if classify_flag(f)}
    fallback_flags = [
        f for f in flags
        if not (classify_flag(f) and classify_flag(f).code in policy_codes)
    ]
    forgery_flags, _ = split_flags(fallback_flags)
    effective = forgery_score_from_flags(forgery_flags) if forgery_flags else 0
    if effective >= FAKE_THRESHOLD or forgery_flags:
        score_out = effective if effective >= FAKE_THRESHOLD else max(effective, FAKE_THRESHOLD)
        return "ФЕЙК", "🔴", score_out, forgery_flags
    return "ЧИСТО", "✅", effective, forgery_flags


def forgery_score_from_flags(forgery_flags: list[str]) -> int:
    total = 0
    for f in forgery_flags:
        fu = f.upper()
        if any(x in fu for x in (
            "W_ARRAY_PRETTY", "W_ARRAY_SERIAL",
            "AMOUNT_MISMATCH", "CMAP_INVALID", "CMAP_W_MISMATCH",
            "MISSING_FROM", "MISSING_REQUIRED", "F3_NOT_ALSRUBL",
            "BROKEN_", "LOCA_", "OVERLAY", "LAYOUT_FAMILY",
            "FOREIGN_PRODUCER", "MULTIPLE_EOF", "PREV_TRAILER",
            "FONTFILE2_CID", "ПЕРЕСОБРАН", "PIKEPDF",
            "CONTENT STREAM НЕ НАЙДЕН", "ЦЕЛОСТНОСТЬ PDF",
            "KEYWORDS", "SBP_OPID", "SBP_CIPHER", "CREATION_EQ", "JAVASCRIPT", "ACROFORM",
            "TBANK_RUBLE_GLYPH", "TBANK_FONT_RENDER", "TBANK_F3_", "TBANK_BT_ET",
            "TBANK_SHELL_PRODUCER", "TBANK_SHELL_CREATOR", "TBANK_SHELL_SUBJECT",
        )):
            total += 95
        elif any(x in fu for x in ("PRODUCER", "MISMATCH", "ANOMALY", "VIOLATION")):
            total += 65
        else:
            total += 50
    return total
