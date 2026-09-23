from detector.tbank_v6.f1_subset_shape import check_f1_subset_shape
from detector.tbank_v6.rules import HARD_CODES


def test_card_unused_drawing_is_a_hard_flag():
    assert "TBANK_F1_CARD_UNUSED_DRAWING" in HARD_CODES


def test_unrelated_pdf_is_not_this_break():
    result = check_f1_subset_shape(b"%PDF-1.4\n")
    assert result.flags == []


def test_label_composite_floor_is_a_hard_flag():
    assert "TBANK_F1_COMPOSITE_FLOOR" in HARD_CODES
