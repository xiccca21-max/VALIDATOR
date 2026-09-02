"""HARD: Jasper Tm spelling — 3+ decimals and truncated template Y."""

from detector.sber_v2.content import audit_jasper_tm_serialization
from detector.sber_v2.rules import HARD_CODES


def _codes(content: bytes, profile: str) -> set[str]:
    return {f.code for f in audit_jasper_tm_serialization(content, profile)}


def test_hard_codes_registered():
    assert "SBER_CONTENT_TM_DECIMAL_OVERFLOW" in HARD_CODES
    assert "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED" in HARD_CODES


def test_genuine_itext_spelling_clean():
    cs = b"1 0 0 1 64.64 615.74 Tm\n1 0 0 1 69.3 632.74 Tm\n1 0 0 1 75.47 711.74 Tm\n"
    assert _codes(cs, "sber_internal_jasper") == set()
    assert _codes(cs, "sbp_outgoing") == set()


def test_three_decimal_x_is_hard():
    cs = b"1 0 0 1 65.390 615.74 Tm\n"
    assert _codes(cs, "sber_internal_jasper") == {
        "SBER_CONTENT_TM_DECIMAL_OVERFLOW",
    }


def test_truncated_template_y_is_hard():
    cs = b"1 0 0 1 64.64 615.7 Tm\n"
    assert _codes(cs, "sber_internal_jasper") == {
        "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED",
    }


def test_proton_both_tells():
    cs = b"1 0 0 1 65.390 615.7 Tm\n1 0 0 1 65.090 711.7 Tm\n"
    assert _codes(cs, "sbp_outgoing") == {
        "SBER_CONTENT_TM_DECIMAL_OVERFLOW",
        "SBER_CONTENT_TM_TEMPLATE_Y_TRUNCATED",
    }


def test_ignores_non_jasper_profiles():
    cs = b"1 0 0 1 65.390 615.7 Tm\n"
    assert _codes(cs, "sber_internal_pdfium") == set()
    assert _codes(cs, "card_other_ios") == set()
    assert _codes(cs, "") == set()


def test_tm_inside_literal_string_ignored():
    cs = b"(1 0 0 1 65.390 615.7 Tm)Tj\n1 0 0 1 64.64 615.74 Tm\n"
    assert _codes(cs, "sber_internal_jasper") == set()
