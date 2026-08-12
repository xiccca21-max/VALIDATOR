"""Regression: SFNT inventory HARD + linked-tuple B1/010/790502."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import VALIDATOR_VERSION, analyze  # noqa: E402
from detector.tbank_sfnt_table_integrity import (  # noqa: E402
    CODE_UNEXPECTED,
    CODE_ZZZZ,
    check_tbank_sfnt_table_inventory,
)
from detector.corpus_profiles import CHANNEL_SBP, detect_receipt_channel  # noqa: E402

try:
    import fitz
except ImportError:
    fitz = None

TEST_DIR = Path(r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\_v3_test15")
CORP = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")


def codes(result: dict) -> list[str]:
    out: list[str] = []
    for f in result.get("flags") or []:
        if isinstance(f, str) and f.startswith("[") and "]" in f:
            out.append(f[1:f.index("]")])
    return out


def main() -> int:
    print("version", VALIDATOR_VERSION)
    assert TEST_DIR.is_dir(), TEST_DIR

    # Acceptance: test_9
    r9 = analyze((TEST_DIR / "receipt_21.07.2026_test_9.pdf").read_bytes())
    c9 = codes(r9)
    print("test_9", r9["verdict"], [c for c in c9 if any(x in c for x in ("TTF", "INERT", "LINKED", "UNEXPECTED"))])
    assert r9["verdict"] == "ФЕЙК"
    assert CODE_ZZZZ in c9 or "TBANK_TTF_INERT_PADDING_TABLE" in c9
    assert "SBP_LINKED_TUPLE_CONFLICT" in c9

    # test_15: ZZZZ but valid linked tuple
    r15 = analyze((TEST_DIR / "receipt_21.07.2026_test_15.pdf").read_bytes())
    c15 = codes(r15)
    print("test_15", r15["verdict"], [c for c in c15 if any(x in c for x in ("TTF", "INERT", "LINKED", "UNEXPECTED"))])
    assert r15["verdict"] == "ФЕЙК"
    assert "TBANK_TTF_INERT_PADDING_TABLE" in c15
    assert "SBP_LINKED_TUPLE_CONFLICT" not in c15

    for n in (6, 8, 16):
        r = analyze((TEST_DIR / f"receipt_21.07.2026_test_{n}.pdf").read_bytes())
        cs = codes(r)
        print(f"test_{n}", r["verdict"], [c for c in cs if "TTF" in c or "INERT" in c])
        assert r["verdict"] == "ФЕЙК"
        assert "TBANK_TTF_INERT_PADDING_TABLE" in cs or CODE_UNEXPECTED in cs

    # Originals: SFNT inventory must not FP
    fp = 0
    sbp_n = 0
    checked = 0
    for p in sorted(CORP.glob("*.pdf")):
        pdf = p.read_bytes()
        if not fitz:
            break
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        is_sbp = (
            detect_receipt_channel(text) == CHANNEL_SBP
            or "идентификатор операции" in text.lower()
        )
        if is_sbp:
            sbp_n += 1
        # Full analyze only for SBP to save time; SFNT gate skips non-SBP anyway
        if not is_sbp:
            inv = check_tbank_sfnt_table_inventory(pdf, text=text)
            assert inv.stats.get("skipped") == "profile_gate" or not inv.flags
            continue
        checked += 1
        inv = check_tbank_sfnt_table_inventory(pdf, text=text)
        if inv.flags:
            fp += 1
            print("FP SFNT", p.name, [f.code for f in inv.flags], inv.stats.get("f1_sfnt_tags"))
        elif not inv.stats.get("inventory_canonical") and not inv.stats.get("skipped"):
            print("WARN non-canonical", p.name, inv.stats.get("f1_sfnt_tags"))

    print(f"sbp_originals={sbp_n} sfnt_checked={checked} fp={fp}")
    assert fp == 0
    print("ACCEPTANCE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
