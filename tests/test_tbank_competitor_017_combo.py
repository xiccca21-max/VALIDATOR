from __future__ import annotations

from pathlib import Path

from detector.tbank import analyze

DOWNLOADS = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
SUSPECTS = [
    DOWNLOADS / "tbank_sbp_08 (7).pdf",
    DOWNLOADS / "tbank_sbp_09 (6).pdf",
    DOWNLOADS / "tbank_sbp_01 (35).pdf",
    DOWNLOADS / "tbank_sbp_02 (21).pdf",
    DOWNLOADS / "tbank_sbp_03 (17).pdf",
    DOWNLOADS / "tbank_sbp_04 (11).pdf",
    DOWNLOADS / "tbank_sbp_05 (9).pdf",
    DOWNLOADS / "tbank_sbp_06 (4).pdf",
    DOWNLOADS / "tbank_sbp_07 (6).pdf",
    DOWNLOADS / "tbank_sbp_08 (6).pdf",
    DOWNLOADS / "tbank_sbp_01 (34).pdf",
    DOWNLOADS / "tbank_sbp_02 (20).pdf",
    DOWNLOADS / "tbank_sbp_03 (16).pdf",
]
GENUINE = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
GENUINE_CONTROL = [GENUINE / "сбп9.pdf", GENUINE / "сбп51.pdf", GENUINE / "сбп54.pdf"]
CODE = "TBANK_COMPETITOR_TUPLE_017_791103_COMBO_003"


def _codes(result: dict) -> list[str]:
    return [
        str(flag).split("]", 1)[0][1:]
        for flag in (result.get("flags") or [])
        if isinstance(flag, str) and flag.startswith("[") and "]" in flag
    ]


def test_competitor_017_combo_hard_on_suspects():
    available = [p for p in SUSPECTS if p.is_file()]
    if not available:
        return
    for path in available:
        result = analyze(path.read_bytes())
        codes = _codes(result)
        assert result["verdict"] == "ФЕЙК", (path.name, result["verdict"], codes)
        assert (
            CODE in codes
            or "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH" in codes
        ), (path.name, codes)


def test_competitor_017_combo_not_on_known_genuines():
    available = [p for p in GENUINE_CONTROL if p.is_file()]
    if not available:
        return
    for path in available:
        result = analyze(path.read_bytes())
        codes = _codes(result)
        assert result["verdict"] == "ЧИСТО", (path.name, result["verdict"], codes)
        assert CODE not in codes, (path.name, codes)
