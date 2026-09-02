"""Yandex OpenPDF CreationDate / YSText full-font metrics catch SEQ clones."""

from pathlib import Path

from detector import route
from detector.sparse9_v1.rules import HARD_CODES
from detector.sparse9_yandex_openpdf import check_yandex_openpdf_invariants

OUT = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\output")
SRC = Path(r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие\фейки яндекс банк.pdf")
GEN = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\яндекс банк")


def _fake_path() -> Path | None:
    for path in (OUT / "fake_yandex.pdf", SRC):
        if path.is_file():
            return path
    return None


def test_yandex_hard_codes_registered():
    assert "YANDEX_CREATION_DATE_FORMAT" in HARD_CODES
    assert "YANDEX_YSTEXT_FULLFONT_METRICS" in HARD_CODES
    assert "YANDEX_KNOWN_FILE_SIGNATURE" in HARD_CODES


def test_seq_yandex_is_fake():
    path = _fake_path()
    if path is None:
        return
    bank, result, _ = route(path.read_bytes())
    flags = result.get("flags") or []
    assert bank == "Яндекс Банк"
    assert result["verdict"] == "ФЕЙК", flags
    joined = " ".join(str(flag) for flag in flags)
    assert "YANDEX_CREATION_DATE_FORMAT" in joined
    assert "YANDEX_YSTEXT_FULLFONT_METRICS" in joined


def test_yandex_genuines_are_clean():
    if not GEN.is_dir():
        return
    scanned = 0
    for path in sorted(GEN.rglob("*.pdf")):
        pdf = path.read_bytes()
        inv = check_yandex_openpdf_invariants(pdf)
        assert not inv.flags, (path.name, [flag.detail for flag in inv.flags])
        _bank, result, _ = route(pdf)
        flags = result.get("flags") or []
        assert result["verdict"] == "ЧИСТО", (path.name, flags)
        scanned += 1
    assert scanned >= 3
