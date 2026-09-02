"""Oracle phone receipts sit between card and SBP content sizes — not a SEQ pad."""

from pathlib import Path

from detector.alfa import analyze
from detector.alfa_v2.content import oracle_decoded_in_midgap
from detector.alfa_v2.rules import HARD_CODES

PHONE_FP = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\output\dokument_10.pdf")
ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
DOWNLOADS_PHONE = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\Документ (10).pdf")


def test_hard_code_still_registered():
    assert "ALFA_ORACLE_CONTENT_MIDGAP" in HARD_CODES


def test_midgap_keeps_seq_card_pads():
    assert oracle_decoded_in_midgap(3545, "card") is True
    assert oracle_decoded_in_midgap(3689, "card") is True
    assert oracle_decoded_in_midgap(4500, "card") is True
    assert oracle_decoded_in_midgap(4500, "sbp") is True
    assert oracle_decoded_in_midgap(4500, "") is True


def test_midgap_spares_known_card_and_sbp_sizes():
    assert oracle_decoded_in_midgap(3413, "card") is False
    assert oracle_decoded_in_midgap(4152, "card") is False
    assert oracle_decoded_in_midgap(5091, "sbp") is False
    assert oracle_decoded_in_midgap(5542, "sbp") is False


def test_midgap_spares_oracle_phone_between_card_and_sbp():
    assert oracle_decoded_in_midgap(4200, "phone") is False
    assert oracle_decoded_in_midgap(4020, "phone") is False
    assert oracle_decoded_in_midgap(4800, "phone") is False


def _phone_pdf() -> Path | None:
    for path in (PHONE_FP, DOWNLOADS_PHONE):
        if path.is_file():
            return path
    return None


def test_oracle_phone_original_is_clean():
    path = _phone_pdf()
    if path is None:
        return
    result = analyze(path.read_bytes())
    flags = result.get("flags") or []
    assert result["verdict"] == "ЧИСТО", flags
    assert not any("ALFA_ORACLE_CONTENT_MIDGAP" in str(flag) for flag in flags)


def test_oracle_corpus_not_midgap():
    if not ORIG.is_dir():
        return
    from detector.alfa_v2.content import check_content
    from detector.alfa_v2.profile_semantics import classify_submethod
    import fitz

    scanned = 0
    for path in sorted(ORIG.rglob("*.pdf")):
        pdf = path.read_bytes()
        if b"Oracle BI Publisher" not in pdf:
            continue
        scanned += 1
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
            producer = doc.metadata.get("producer") or ""
        content = check_content(
            pdf,
            producer=producer,
            method=classify_submethod(text),
        )
        assert not any(
            flag.code == "ALFA_ORACLE_CONTENT_MIDGAP" for flag in content.flags
        ), (path.name, [flag.format() for flag in content.flags])
    assert scanned >= 14
