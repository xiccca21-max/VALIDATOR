"""Malformed TinkoffSans glyf trailing data is a standalone hard signal."""

from pathlib import Path

from detector.tbank_v6.sbp_competitor_hard import (
    STANDALONE_GLYF_CODE,
    _TARGET_TUPLE,
    _TARGET_TUPLES,
    _nonbenign_residue_match,
    _residue_match,
    check_sbp_competitor_hard,
)

ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк\сбп1.pdf")


def test_tuple_without_glyf_warn_is_not_hard():
    assert _residue_match(_TARGET_TUPLE, []) is False
    assert _residue_match(_TARGET_TUPLE, [405]) is False
    assert _residue_match(_TARGET_TUPLE, [500]) is True
    assert _residue_match("1|0|0|G1|002|00117|791103", [95]) is True
    assert _residue_match("0|6|0|G1|004|00117|770901", [500]) is False
    assert _TARGET_TUPLE in _TARGET_TUPLES


def test_nonbenign_glyf_residue_does_not_require_target_tuple():
    assert _nonbenign_residue_match([]) is False
    assert _nonbenign_residue_match([405]) is False
    assert _nonbenign_residue_match([131]) is True


def test_genuine_sbp1_openpdf_clean():
    if not ORIG.is_file():
        return
    pdf = ORIG.read_bytes()
    import fitz
    text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
    res = check_sbp_competitor_hard(pdf, text)
    assert res.stats["tuple7"] == _TARGET_TUPLE
    assert res.stats["warn_count"] == 0
    assert res.flags == []


def test_new_002_791103_suspects_have_glyf_residue():
    downloads = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
    suspects = [
        downloads / "tbank_sbp_03 (19).pdf",
        downloads / "tbank_sbp_02 (23).pdf",
        downloads / "tbank_sbp_01 (42).pdf",
    ]
    for path in suspects:
        if not path.is_file():
            continue
        pdf = path.read_bytes()
        import fitz
        text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
        res = check_sbp_competitor_hard(pdf, text)
        assert res.stats["tuple7"] == "1|0|0|G1|002|00117|791103"
        assert res.stats["warn_values"] in ([95], [97], [273])
        assert res.flags


def test_slot018_native_tuple_requires_physical_glyf_residue():
    fake = Path(
        r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
        r"\output\defender_inbox\206831_tbank_sbp_01.pdf"
    )
    if fake.is_file():
        pdf = fake.read_bytes()
        import fitz
        text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
        res = check_sbp_competitor_hard(pdf, text)
        assert res.stats["tuple7"] == "0|H|0|G1|018|00117|791103"
        assert res.stats["warn_values"] == [115]
        assert res.flags

    for genuine in (
        Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк\сбп15.pdf"),
        Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк\сбп55.pdf"),
    ):
        if not genuine.is_file():
            continue
        pdf = genuine.read_bytes()
        import fitz
        text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
        res = check_sbp_competitor_hard(pdf, text)
        assert res.stats["warn_count"] == 0
        assert res.flags == []


def test_slot005_770901_fake_requires_physical_glyf_residue():
    fake = Path(
        r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
        r"\output\defender_inbox\206928_tbank_sbp_01.pdf"
    )
    if not fake.is_file():
        return
    pdf = fake.read_bytes()
    import fitz
    text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
    res = check_sbp_competitor_hard(pdf, text)
    assert res.stats["tuple7"] == "0|1|0|G1|005|00117|770901"
    assert res.stats["warn_values"] == [131]
    assert [code for code, _ in res.flags] == [STANDALONE_GLYF_CODE]


def test_genuine_002_791103_has_no_glyf_residue():
    path = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк\сбп11.pdf")
    if not path.is_file():
        return
    pdf = path.read_bytes()
    import fitz
    text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
    res = check_sbp_competitor_hard(pdf, text)
    assert res.stats["tuple7"] == "1|0|0|G1|002|00117|791103"
    assert res.stats["warn_count"] == 0
    assert res.flags == []
