# -*- coding: utf-8 -*-
"""ЮMoney page size: card ~713 and phone/SBP ~861 are both live."""
from __future__ import annotations

from pathlib import Path

from detector import route

_DIR = Path(r"c:\Users\fanis\OneDrive\Desktop\чеки\юмани банк")


def _pdf(name_part: str) -> bytes:
    hits = [p for p in _DIR.glob("*.pdf") if name_part in p.name]
    assert hits, f"missing {name_part} under {_DIR}"
    return hits[0].read_bytes()


def test_yoomoney_card_713_clean():
    bank, r, _ = route(_pdf("0_33_3"))
    assert bank == "ЮMoney"
    assert r.get("verdict") == "ЧИСТО"
    assert not r.get("flags")


def test_yoomoney_phone_sbp_861_clean():
    bank, r, _ = route(_pdf("0_33_27"))
    assert bank == "ЮMoney"
    assert r.get("verdict") == "ЧИСТО", r.get("flags")
    assert not any("PAGE_MISMATCH" in str(f) for f in (r.get("flags") or []))
