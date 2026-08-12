"""
Corpus-derived validation signals.

These compare a receipt against hashes/templates collected from training originals.
They are useful for analysts and catching known generator clones, but a new genuine
receipt (new name, amount, skeleton variant, F1 subset) can legitimately fall outside
the corpus — they must never alone drive verdict ФЕЙК.
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]")


def flag_code(flag: str) -> str | None:
    m = _CODE_RE.match((flag or "").strip())
    return m.group(1) if m else None


# Exact codes that are corpus/stat-only (never forgery by themselves).
CORPUS_STAT_CODES = frozenset({
    "FF2_SUBSET_UNKNOWN",
    "FONT_AUTH_FOREIGN_FONT",
    "FONT_AUTH_NAME_DRIFT",
    "FONT_AUTH_TABLE_DRIFT",
    "BANK_CONTENT_SKELETON_UNKNOWN",
    "BANK_OBJECT_COUNT_OUTLIER",
    "BANK_CONTENT_STREAM_OUTLIER",
    "BANK_FILE_SIZE_OUTLIER",
    "BANK_FONTFILE2_COUNT_OUTLIER",
    "BANK_FONTFILE2_SIZE_OUTLIER",
    "BANK_FONTFILE2_NAME_MISMATCH",
    "BANK_PRODUCER_MISMATCH",
    "TBANK_CHANNEL_SKELETON_UNKNOWN",
    "TBANK_CONTENT_SKELETON_UNKNOWN",
    "TBANK_LAYERED_PROFILE_FORGERY",
    "TBANK_REASSEMBLY_FORGERY",
    "TBANK_FONT_RENDER_FORGERY",
    "TBANK_RENDER_FOREIGN_ROWS",
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
    "PROFILE_CLUSTER_OUTLIER",
    "CONTENT_STREAM_PROFILE_MISMATCH",
    "ALFA_PRODUCER_MISMATCH",
    "ALFA_CONTENT_STREAM_OUTLIER",
    "ALFA_OBJECT_COUNT_OUTLIER",
    "ALFA_FONTFILE2_COUNT_OUTLIER",
    "ALFA_FONTFILE2_SIZE_OUTLIER",
    "ALFA_FONTFILE2_NAME_MISMATCH",
    "ALFA_IMAGE_LAYOUT_MISMATCH",
    "TBANK_COORDINATE_DRIFT",
    "TBANK_RIGHT_EDGE_DRIFT",
    "TBANK_BASELINE_DRIFT",
    "TBANK_OPERATOR_FINGERPRINT",
    "TBANK_F1_HMTX_DRIFT",
    "TBANK_F2_HMTX_DRIFT",
    "TBANK_F1_HEAD_DRIFT",
    "TBANK_F2_HEAD_DRIFT",
    "TBANK_F1_MAXP_DRIFT",
    "TBANK_F2_MAXP_DRIFT",
    "TBANK_F1_W_ARRAY_UNKNOWN",
    "TBANK_F2_W_ARRAY_UNKNOWN",
    "SBER_SBP_OPERATOR_DRIFT",
    "SBER_SBP_LAYOUT_DRIFT",
})

CORPUS_STAT_PREFIXES = (
    "GLYPH_TTF_",
    "GLYPH_PIX_",
    "SYMBOL_",
    "TBANK_TEMPLATE_",
    "TBANK_F1_",
    "TBANK_F2_",
    "CLUSTER_",
    "NOT_OBSERVED",
)


def is_corpus_stat_code(code: str) -> bool:
    if not code:
        return False
    if code in CORPUS_STAT_CODES:
        return True
    if code.startswith("TBANK_F3_"):
        return False
    return any(code.startswith(p) for p in CORPUS_STAT_PREFIXES)


def is_corpus_stat_flag(flag: str) -> bool:
    code = flag_code(flag)
    if code and is_corpus_stat_code(code):
        return True
    fl = (flag or "").lower()
    if "не в корпусе" in fl or "не встречал" in fl and "эталон" in fl:
        return True
    if "corpus whitelist" in fl:
        return True
    return False


def append_stats_only(details: dict, flag_line: str) -> None:
    details.setdefault("stats_only", []).append(flag_line)


def emit_check(
    details: dict,
    flags: list[str],
    flag_line: str,
    score_delta: int = 0,
) -> int:
    """Route corpus-stat flags to stats_only; invariant flags to flags[]."""
    if is_corpus_stat_flag(flag_line):
        append_stats_only(details, flag_line)
        return 0
    flags.append(flag_line)
    return score_delta
