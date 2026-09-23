"""T-Bank SEQ passers: NSPK route_marker digit + JRXML date/Перевод.

Not novelty (glyf size / skeleton). 0 FP on OpenPDF genuines: ID[14] is
always a digit (n=60 SBP) and first line is always DD.MM.YYYY (n=133).
"""

from __future__ import annotations

from pathlib import Path

from detector.sbp_cipher import extract_sbp_opid
from detector.tbank import analyze
from detector.tbank_id_reuse import (
    _CANONICAL_ID_CONTENT_SHA256,
    check_trailer_id_reuse,
)
from detector.tbank_sbp_content import validate_tbank_sbp_id
from detector.tbank_reassembly_family_v3 import _F2_GLYF_FAT_BY_CARD
from detector.tbank_v6.content_profile import check_content_profile
from detector.tbank_v6.rules import HARD_CODES, IGNORED_CODES

DOWNLOADS = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
FAKE05 = DOWNLOADS / "tbank_sbp_05 (3).pdf"
FAKE01 = DOWNLOADS / "tbank_sbp_01 (6).pdf"
ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")

_PRODUCER = "OpenPDF 1.3.30.jaspersoft.2"
_CREATOR = "JasperReports Library version 6.20.3"


def test_date_line_and_perevod_are_hard():
    assert "TBANK_DATE_LINE_CORRUPTED" in HARD_CODES
    assert "TBANK_STATIC_LABEL_CORRUPTED" in HARD_CODES
    assert "SBP_CIPHER_STRUCTURE" in HARD_CODES
    assert "SBP_REFERENCE_NON_NUMERIC" in HARD_CODES
    assert "SBP_PROFILE_EPOCH_EXPIRED" in HARD_CODES
    assert "SBP_PROFILE_EPOCH_SUFFIX_CONFLICT" in HARD_CODES
    assert "SBP_PROFILE_SUFFIX_OWNER_CONFLICT" in HARD_CODES
    assert "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT" in HARD_CODES


def test_overfit_atlas_rules_are_not_hard():
    """Finite genuines atlas / common card last4 must not decide ФЕЙК."""
    assert "TBANK_CARD_LAST4_SEQUENTIAL" not in HARD_CODES
    assert "TBANK_CARD_LAST4_SEQUENTIAL" in IGNORED_CODES
    assert "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH" not in HARD_CODES
    assert "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH" in IGNORED_CODES
    assert _F2_GLYF_FAT_BY_CARD[5] >= 1654
    assert _F2_GLYF_FAT_BY_CARD[2] >= 1190


def test_fake05_letter_route_marker_and_garbled_text():
    if not FAKE05.is_file():
        return
    pdf = FAKE05.read_bytes()
    result = analyze(pdf)
    flags = " ".join(str(f) for f in (result.get("flags") or []))
    assert result["verdict"] == "ФЕЙК", (result["verdict"], flags)
    assert (
        "SBP_CIPHER_STRUCTURE" in flags
        or "TBANK_DATE_LINE_CORRUPTED" in flags
        or "TBANK_STATIC_LABEL_CORRUPTED" in flags
    ), flags


def test_route_marker_letter_unit():
    """G1/00117 ID with letter at [14] is NSPK-broken even if class/bank5 known."""
    opid = "A6226005706ODBW10G10050011770901"
    assert len(opid) == 32
    assert not opid[14].isdigit()
    res = validate_tbank_sbp_id(
        opid, "14.08.2026  03:57:05\nИтого\n", b"",
        producer=_PRODUCER, creator=_CREATOR,
    )
    codes = [f.code for f in res.flags]
    assert "SBP_CIPHER_STRUCTURE" in codes


def test_reference_block_must_be_three_decimal_digits():
    genuine = "B61801427169801S0G10180011791103"
    fake = "B623210500990A1S0G10180011791103"
    for opid, should_flag in ((genuine, False), (fake, True)):
        res = validate_tbank_sbp_id(
            opid, "", b"", producer=_PRODUCER, creator=_CREATOR,
        )
        codes = [f.code for f in res.flags]
        assert ("SBP_REFERENCE_NON_NUMERIC" in codes) is should_flag


def test_retired_00117_791103_profile_cannot_claim_august_epoch():
    cases = (
        ("A6180170116606100G10020011791103", "29.06.2026  20:01:16\n", False),
        ("B6233110907503170G10120011831501", "21.08.2026  14:09:07\n", False),
        ("B6232103330717100G10020011791103", "20.08.2026  13:33:29\n", True),
    )
    for opid, text, should_flag in cases:
        res = validate_tbank_sbp_id(
            opid, text, b"", producer=_PRODUCER, creator=_CREATOR,
        )
        codes = [f.code for f in res.flags]
        assert ("SBP_PROFILE_EPOCH_EXPIRED" in codes) is should_flag


def test_august_00118_rejects_stale_891103_suffix_graft():
    cases = (
        ("B6233110907503170G10120011831501", "21.08.2026  14:09:07\n", False),
        ("B62240812416250Y0B10140011821301", "12.08.2026  11:12:41\n", False),
        ("A6228193054688100G10020011891103", "16.08.2026  22:30:53\n", True),
    )
    for opid, text, should_flag in cases:
        res = validate_tbank_sbp_id(
            opid, text, b"", producer=_PRODUCER, creator=_CREATOR,
        )
        codes = [f.code for f in res.flags]
        assert ("SBP_PROFILE_EPOCH_SUFFIX_CONFLICT" in codes) is should_flag


def test_august_821301_suffix_stays_with_its_owner_tuple():
    cases = (
        ("B62240812416250Y0B10140011821301", "12.08.2026  11:12:41\n", False),
        ("B6228184711762100G10020011821301", "16.08.2026  21:47:11\n", True),
    )
    for opid, text, should_flag in cases:
        res = validate_tbank_sbp_id(
            opid, text, b"", producer=_PRODUCER, creator=_CREATOR,
        )
        codes = [f.code for f in res.flags]
        assert ("SBP_PROFILE_SUFFIX_OWNER_CONFLICT" in codes) is should_flag


def test_g1_slot018_route_binding_unit():
    """Known G1 route 018 accepts H/0,S/1; competitor marker/control rotation does not."""
    genuine_pairs = (
        "B61801427169801S0G10180011791103",
        "B61800741112420H0G10180011791103",
    )
    fake_rotated = "B61801427169802A0G10180011791103"
    for opid in genuine_pairs:
        res = validate_tbank_sbp_id(
            opid, "", b"", producer=_PRODUCER, creator=_CREATOR,
        )
        assert "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT" not in [
            f.code for f in res.flags
        ]
    res = validate_tbank_sbp_id(
        fake_rotated, "", b"", producer=_PRODUCER, creator=_CREATOR,
    )
    assert "TBANK_SBP_G1_SLOT018_BINDING_CONFLICT" in [
        f.code for f in res.flags
    ]


def test_canonical_trailer_identity_binds_original_content():
    assert len(_CANONICAL_ID_CONTENT_SHA256) >= 120
    for genuine in (ORIG / "сбп.pdf", ORIG / "сбп15.pdf"):
        if not genuine.is_file():
            continue
        result = check_trailer_id_reuse(
            genuine.read_bytes(),
            "",
            producer=_PRODUCER,
            creator=_CREATOR,
        )
        assert "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH" not in [
            f.code for f in result.flags
        ]

    inbox = Path(__file__).resolve().parents[1] / "output" / "defender_inbox"
    for fake in (
        inbox / "206836_tbank_sbp_01.pdf",
        inbox / "206861_tbank_sbp_01.pdf",
        inbox / "206866_tbank_sbp_02.pdf",
        inbox / "206881_tbank_sbp_01.pdf",
    ):
        if not fake.is_file():
            continue
        result = check_trailer_id_reuse(
            fake.read_bytes(),
            "",
            producer=_PRODUCER,
            creator=_CREATOR,
        )
        assert "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH" in [
            f.code for f in result.flags
        ]


def test_fake01_native_clone_not_caught_by_emitter_laws():
    """Full Jasper clone: valid NSPK ID, intact ToUnicode. No generator law."""
    if not FAKE01.is_file():
        return
    result = analyze(FAKE01.read_bytes())
    flags = " ".join(str(f) for f in (result.get("flags") or []))
    assert result["verdict"] == "ЧИСТО", flags
    assert "SBP_CIPHER_STRUCTURE" not in flags
    assert "TBANK_DATE_LINE_CORRUPTED" not in flags
    assert "TBANK_STATIC_LABEL_CORRUPTED" not in flags


def test_openpdf_genuines_no_new_hard():
    if not ORIG.is_dir():
        return
    n = 0
    for path in ORIG.rglob("*.pdf"):
        pdf = path.read_bytes()
        if b"OpenPDF" not in pdf:
            continue
        n += 1
        cp = check_content_profile(pdf)
        hard = [f.code for f in cp.flags if f.code in (
            "TBANK_DATE_LINE_CORRUPTED",
            "TBANK_STATIC_LABEL_CORRUPTED",
        )]
        assert not hard, (path.name, hard, [f.detail for f in cp.flags])
        import fitz
        text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
        if "Идентификатор" not in text:
            continue
        opid = extract_sbp_opid(text) or ""
        if len(opid) != 32:
            continue
        sbp = validate_tbank_sbp_id(
            opid, text, pdf, producer=_PRODUCER, creator=_CREATOR,
        )
        struct = [f.code for f in sbp.flags if f.code == "SBP_CIPHER_STRUCTURE"
                  and "позиц" in (f.detail or "")]
        assert not struct, (path.name, opid, [f.detail for f in sbp.flags])
    assert n >= 100
