"""Ozon G101 SBP tail is not a fake tell — live Skia originals use it."""

from pathlib import Path

from detector.ozon import analyze
from detector.ozon_v1.rules import DIAGNOSTIC_CODES, HARD_CODES

OZON = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\озон чекии")


def test_cross_bank_tail_not_hard():
    assert "OZON_SBP_ID_CROSS_BANK_TAIL" not in HARD_CODES
    assert "OZON_SBP_ID_CROSS_BANK_TAIL" in DIAGNOSTIC_CODES


def test_g101_skia_originals_are_clean():
    if not OZON.is_dir():
        return
    scanned = 0
    for name in ("sbp.pdf", "sbp1.pdf"):
        path = OZON / name
        if not path.is_file():
            continue
        scanned += 1
        result = analyze(path.read_bytes())
        flags = result.get("flags") or []
        assert result["verdict"] == "ЧИСТО", (name, flags)
        assert not any("OZON_SBP_ID_CROSS_BANK_TAIL" in str(f) for f in flags)
    if scanned:
        assert scanned == 2
