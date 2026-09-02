"""HARD: Oracle SBP Tahoma unique hmtx advances floor."""

from pathlib import Path

from detector.alfa import analyze
from detector.alfa_v2.rules import HARD_CODES

FAKE = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\alfa_sbp_114100.pdf")
ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")


def test_hard_code_registered():
    assert "ALFA_ORACLE_SBP_HMTX_UNIQ_ADVANCES" in HARD_CODES


def test_proton_fake_is_hard():
    if not FAKE.is_file():
        return
    result = analyze(FAKE.read_bytes())
    assert result["verdict"] == "ФЕЙК"
    assert any(
        "ALFA_ORACLE_SBP_HMTX_UNIQ_ADVANCES" in flag
        for flag in (result.get("flags") or [])
    )


def test_oracle_sbp_originals_stay_clean():
    if not ORIG.is_dir():
        return
    from detector.alfa_v2.fonts import check_fonts

    scanned = 0
    for path in sorted(ORIG.rglob("*.pdf")):
        pdf = path.read_bytes()
        if b"Oracle BI Publisher" not in pdf:
            continue
        if not (57_000 <= len(pdf) <= 59_200):
            continue
        scanned += 1
        fonts = check_fonts(pdf, producer="Oracle BI Publisher 12.2.1.4.0")
        assert not any(
            flag.code == "ALFA_ORACLE_SBP_HMTX_UNIQ_ADVANCES" for flag in fonts.flags
        ), (path.name, [flag.format() for flag in fonts.flags])
    assert scanned >= 10


def test_oracle_card_originals_below_sbp_floor_not_flagged():
    card = ORIG / "альфа карта.pdf"
    if not card.is_file():
        return
    from detector.alfa_v2.fonts import check_fonts

    fonts = check_fonts(card.read_bytes(), producer="Oracle BI Publisher 12.2.1.4.0")
    assert not any(
        flag.code == "ALFA_ORACLE_SBP_HMTX_UNIQ_ADVANCES" for flag in fonts.flags
    )
