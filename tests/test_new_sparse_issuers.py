"""New sparse issuers: MTS Dengi, YooMoney, Russian Standard, Tochka + Raif empty-producer."""

from pathlib import Path

from detector import route
from detector.profiles import format_banks_list_html, identify, reload_profiles
from detector.sparse9_profiles import detect_issuer, extract_sbp_opid
from detector.sparse9_v1.rules import HARD_CODES

CHECKS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
MTS = CHECKS / "мтс деньги"
YOOMONEY = CHECKS / "юмани банк"
RS = CHECKS / "русский стандарт"
TOCHKA = CHECKS / "точка банк"
RAIF = CHECKS / "райф"
SBER = CHECKS / "сбер"
YANDEX = CHECKS / "яндекс банк"
TBANK = CHECKS / "т банк"


def _first_pdf(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    pdfs = sorted(folder.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def test_hard_codes_registered():
    for code in (
        "MTS_PRODUCER_MISMATCH", "MTS_FONT_MISMATCH", "MTS_PAGE_MISMATCH",
        "YOOMONEY_PRODUCER_MISMATCH", "YOOMONEY_FONT_MISMATCH",
        "RSBANK_PRODUCER_MISMATCH", "RSBANK_ISSUER_BIK_MISMATCH",
        "TOCHKA_FONT_MISMATCH", "TOCHKA_ISSUER_BIK_MISMATCH",
    ):
        assert code in HARD_CODES


def test_bot_bank_list_includes_new_issuers():
    html = format_banks_list_html()
    for name in ("Т-Банк", "Альфа-Банк", "Сбербанк", "МТС Деньги", "ЮMoney",
                 "Русский Стандарт", "Точка Банк", "ВБ Банк", "Райффайзенбанк"):
        assert name in html, name


def _assert_clean(folder: Path, bank_name: str, engine: str = "sparse9_v1") -> None:
    reload_profiles()
    scanned = 0
    shas: set[str] = set()
    for path in sorted(folder.glob("*.pdf")):
        pdf = path.read_bytes()
        sha = path.stat().st_size
        key = (sha, pdf[:64])
        if key in shas:
            continue
        shas.add(key)
        bank, result, _ = route(pdf)
        flags = result.get("flags") or []
        assert bank == bank_name, (path.name, bank, flags)
        assert result["verdict"] == "ЧИСТО", (path.name, flags)
        assert (result.get("details") or {}).get("engine") == engine
        scanned += 1
    assert scanned >= 1


def test_mts_genuine_is_clean():
    if not MTS.is_dir():
        return
    path = _first_pdf(MTS)
    assert path is not None
    opid = extract_sbp_opid(
        "Код операции СБП\nA62160751543140J0G1000001\n1820705"
    )
    assert opid == "A62160751543140J0G10000011820705"
    _assert_clean(MTS, "МТС Деньги")


def test_yoomoney_genuine_is_clean_not_sber():
    if not YOOMONEY.is_dir():
        return
    path = _first_pdf(YOOMONEY)
    assert path is not None
    pdf = path.read_bytes()
    import fitz
    doc = fitz.open(stream=pdf, filetype="pdf")
    producer = doc.metadata.get("producer") or ""
    creator = doc.metadata.get("creator") or ""
    text = doc[0].get_text()
    doc.close()
    prof, score = identify(text, producer, creator, pdf)
    assert prof and prof["key"] == "yoomoney", (prof, score)
    assert detect_issuer(text, producer, creator, pdf) == "yoomoney"
    _assert_clean(YOOMONEY, "ЮMoney")


def test_rsbank_genuine_is_clean():
    if not RS.is_dir():
        return
    _assert_clean(RS, "Русский Стандарт")


def test_tochka_genuine_is_clean():
    if not TOCHKA.is_dir():
        return
    _assert_clean(TOCHKA, "Точка Банк")


def test_raif_empty_producer_genuine_is_clean():
    path = RAIF / "райф СБП.pdf"
    if not path.is_file():
        return
    pdf = path.read_bytes()
    bank, result, _ = route(pdf)
    flags = result.get("flags") or []
    assert bank == "Райффайзенбанк", (bank, flags)
    assert result["verdict"] == "ЧИСТО", flags


def test_yandex_not_stolen_by_tochka():
    if not YANDEX.is_dir():
        return
    path = _first_pdf(YANDEX)
    if path is None:
        return
    bank, result, _ = route(path.read_bytes())
    assert bank == "Яндекс Банк"
    assert result["verdict"] == "ЧИСТО"


def test_sber_not_stolen_by_yoomoney():
    if not SBER.is_dir():
        return
    path = _first_pdf(SBER)
    if path is None:
        return
    bank, result, _ = route(path.read_bytes())
    assert bank == "Сбербанк"
    assert result["verdict"] == "ЧИСТО"


def test_tbank_not_stolen_by_mts():
    if not TBANK.is_dir():
        return
    path = _first_pdf(TBANK)
    if path is None:
        return
    bank, result, _ = route(path.read_bytes())
    assert bank == "Т-Банк"
    assert result["verdict"] == "ЧИСТО"


def test_mts_wrong_producer_is_fake():
    path = _first_pdf(MTS) if MTS.is_dir() else None
    if path is None:
        return
    pdf = path.read_bytes().replace(b"dbo-print-forms", b"xxx-print-forms", 1)
    bank, result, _ = route(pdf)
    assert bank == "МТС Деньги"
    joined = " ".join(str(f) for f in (result.get("flags") or []))
    assert result["verdict"] == "ФЕЙК"
    assert "MTS_PRODUCER_MISMATCH" in joined


def test_yoomoney_bad_producer_and_creation_date_are_fake():
    path = _first_pdf(YOOMONEY) if YOOMONEY.is_dir() else None
    if path is None:
        return
    pdf = path.read_bytes().replace(b"iText 2.1.7", b"iText 9.9.9", 1)
    bank, result, _ = route(pdf)
    assert bank == "ЮMoney"
    joined = " ".join(str(f) for f in (result.get("flags") or []))
    assert result["verdict"] == "ФЕЙК"
    assert "YOOMONEY_PRODUCER_MISMATCH" in joined

    pdf = path.read_bytes().replace(b"/CreationDate(D:", b"/CreationDate(X:", 1)
    bank, result, _ = route(pdf)
    joined = " ".join(str(f) for f in (result.get("flags") or []))
    assert result["verdict"] == "ФЕЙК", joined
    assert "YOOMONEY_CREATION_DATE_FORMAT" in joined
