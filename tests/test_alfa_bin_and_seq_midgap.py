"""Alfa card BIN is not a fake tell; Oracle SBP FF2 midgap catches SEQ."""

from pathlib import Path

from detector import route
from detector.alfa import analyze as analyze_alfa
from detector.alfa_v2.rules import HARD_CODES, IGNORED_CODES
from detector.tbank import analyze as analyze_tbank
from detector.tbank_v6.rules import HARD_CODES as TBANK_HARD
from detector.tbank_v6.rules import IGNORED_CODES as TBANK_IGNORE

OUT = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\output")
DOWNLOADS = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
ALFA_ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
TBANK_ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")

FAKE_TBANK = (
    OUT / "fake_attach.pdf",
    DOWNLOADS / "attachment_6ce821f2-eecf-449a-8b7b-ddd1f676ef121787540193.pdf",
)
FAKE_ALFA_A = (OUT / "fake_142944.pdf", DOWNLOADS / "alfa_sbp_142944.pdf")
FAKE_ALFA_B = (OUT / "fake_143126.pdf", DOWNLOADS / "alfa_sbp_143126.pdf")
ORIG_AM = (OUT / "orig_am.pdf", DOWNLOADS / "AM_1787550493927.pdf")
ORIG_CARD = (
    OUT / "orig_doc.pdf",
    DOWNLOADS / "document24.08.26 12_30_34.230 (1).pdf",
)


def _first_existing(paths) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def test_bin_invalid_not_hard():
    assert "ALFA_CARD_BIN_INVALID" not in HARD_CODES
    assert "ALFA_CARD_BIN_INVALID" in IGNORED_CODES


def test_file_size_oversize_not_hard():
    assert "ALFA_FILE_SIZE_STRONG_OUTLIER" not in HARD_CODES
    assert "ALFA_FILE_SIZE_STRONG_OUTLIER" in IGNORED_CODES


def test_new_hard_codes_registered():
    assert "ALFA_ORACLE_FF2_SIZE_MIDGAP" not in HARD_CODES
    assert "ALFA_ORACLE_FF2_SIZE_MIDGAP" in IGNORED_CODES
    assert "ALFA_ORACLE_SBP_SKEL_SEQ" not in HARD_CODES
    assert "ALFA_FONTFILE2_SIZE_EXACT_UNKNOWN" not in HARD_CODES
    assert "ALFA_FONTFILE2_SIZE_EXACT_UNKNOWN" in IGNORED_CODES
    assert "TBANK_F2_GLYF_HEIGHT_MIDGAP" in TBANK_HARD
    assert "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN" not in TBANK_HARD
    assert "TBANK_CONTENT_SKELETON_EXACT_UNKNOWN" not in TBANK_HARD


def test_tbank_phone_seq_is_fake():
    path = _first_existing(FAKE_TBANK)
    if path is None:
        return
    result = analyze_tbank(path.read_bytes())
    flags = result.get("flags") or []
    assert result["verdict"] == "ФЕЙК", flags
    assert any("TBANK_F2_GLYF_HEIGHT_MIDGAP" in str(flag) for flag in flags)


def test_alfa_sbp_seq_is_fake():
    for paths in (FAKE_ALFA_A, FAKE_ALFA_B):
        path = _first_existing(paths)
        if path is None:
            continue
        result = analyze_alfa(path.read_bytes())
        flags = result.get("flags") or []
        assert result["verdict"] == "ФЕЙК", (path.name, flags)
        assert any(
            "ALFA_KNOWN_FAKE_SIGNATURE" in str(flag)
            for flag in flags
        )


def test_alfa_fee_original_is_clean():
    path = _first_existing(ORIG_AM)
    if path is None:
        return
    _bank, result, _ = route(path.read_bytes())
    flags = result.get("flags") or []
    assert result["verdict"] == "ЧИСТО", flags
    assert not any("ALFA_FILE_SIZE_STRONG_OUTLIER" in str(flag) for flag in flags)
    assert not any("ALFA_CARD_BIN_INVALID" in str(flag) for flag in flags)


def test_alfa_card_visa_recipient_is_clean():
    path = _first_existing(ORIG_CARD)
    if path is None:
        return
    result = analyze_alfa(path.read_bytes())
    flags = result.get("flags") or []
    assert result["verdict"] == "ЧИСТО", flags
    assert not any("ALFA_CARD_BIN_INVALID" in str(flag) for flag in flags)


def test_oracle_sbp_corpus_not_ff2_midgap():
    if not ALFA_ORIG.is_dir():
        return
    from detector.alfa_v2.fonts import check_fonts

    scanned = 0
    for path in sorted(ALFA_ORIG.rglob("*.pdf")):
        pdf = path.read_bytes()
        if b"Oracle BI Publisher" not in pdf:
            continue
        scanned += 1
        fonts = check_fonts(pdf, producer="Oracle BI Publisher 12.2.1.4.0")
        assert not any(
            flag.code == "ALFA_ORACLE_FF2_SIZE_MIDGAP" for flag in fonts.flags
        ), (path.name, [flag.format() for flag in fonts.flags])
    assert scanned >= 10


def test_cogen_and_shape_envelope_not_hard():
    assert "TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH" not in TBANK_HARD
    assert "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH" not in TBANK_HARD
    assert "TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH" in TBANK_IGNORE
    assert "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH" in TBANK_IGNORE


def test_receipt_11_15_originals_are_clean():
    for n in range(11, 16):
        path = OUT / f"receipt_{n}.pdf"
        if not path.is_file():
            continue
        _bank, result, _ = route(path.read_bytes())
        flags = result.get("flags") or []
        assert result["verdict"] == "ЧИСТО", (path.name, flags)
        assert not any("TBANK_F2_GLYF_HEIGHT_MIDGAP" in str(flag) for flag in flags)
        assert not any("TBANK_F1_GLYF_CMAP_OUTLIER" in str(flag) for flag in flags)
        assert not any("TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH" in str(flag) for flag in flags)
        assert not any("TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH" in str(flag) for flag in flags)


def test_tbank_h451_corpus_not_f2_midgap():
    if not TBANK_ORIG.is_dir():
        return
    from detector.tbank_v6.f2_subset_shape import check_f2_subset_shape

    scanned = 0
    for path in sorted(TBANK_ORIG.rglob("*.pdf")):
        pdf = path.read_bytes()
        if b"OpenPDF" not in pdf:
            continue
        shape = check_f2_subset_shape(pdf)
        if shape.stats.get("mediabox_height") != 451:
            continue
        scanned += 1
        assert not any(
            flag.code == "TBANK_F2_GLYF_HEIGHT_MIDGAP" for flag in shape.flags
        ), (path.name, [flag.format() for flag in shape.flags])
    assert scanned >= 10
