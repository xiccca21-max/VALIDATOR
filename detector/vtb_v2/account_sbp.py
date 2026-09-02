# -*- coding: utf-8 -*-
"""VTB OpenPDF 2.x «перевод на счёт в другом банке через СБП».

A second native SBP family next to openhtml «Исходящий перевод СБП»:

* Producer OpenPDF 2.0.x, PDF 1.5, A4, /Title Чек
* Fonts subset Arial-BoldMT + ArialMT with full hinting (cvt/fpgm/prep)
* Fieldset: счёт списания, счёт получателя, номер телефона, сумма зачисления,
  комиссия, сумма, статус, ID операции в СБП, штамп ИСПОЛНЕНО
* NSPK bank5 = 00118 (openhtml phone/SBP stays 00117)

Novelty of subset tags / file size is not a fake. HARD only generator breaks.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .subtypes import SUBTYPE_SBP_ACCOUNT, normalize_text
from .types import VtbFlag
from ..structure import find_streams

_HINT = ("cvt ", "fpgm", "prep")
_AMOUNT_RE = re.compile(
    r"([\d\s\u00a0\u202f]+(?:[.,]\d{2})?)\s*(?:руб|₽)?",
    re.IGNORECASE,
)


@dataclass
class AccountSbpResult:
    flags: list[VtbFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _flag(code: str, detail: str) -> VtbFlag:
    return VtbFlag(code=code, detail=detail, tier="HARD", rule_id=code)


def _sfnt_tags(ttf: bytes) -> tuple[str, ...]:
    if len(ttf) < 12:
        return ()
    n = struct.unpack(">H", ttf[4:6])[0]
    if n <= 0 or 12 + n * 16 > len(ttf):
        return ()
    return tuple(
        ttf[12 + i * 16 : 16 + i * 16].decode("latin1", "replace")
        for i in range(n)
    )


def _mediabox_height(pdf_bytes: bytes) -> float | None:
    m = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]",
        pdf_bytes or b"",
    )
    if not m:
        return None
    try:
        return float(m.group(4))
    except ValueError:
        return None


def _labeled_amount(text: str, label: str) -> float | None:
    raw = normalize_text(text)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    target = label.lower()
    for i, ln in enumerate(lines):
        if ln.lower() == target or ln.lower().rstrip(":") == target:
            for nxt in lines[i + 1 : i + 3]:
                if nxt.lower() in {
                    "сумма", "сумма зачисления", "сумма комиссии",
                    "сообщение получателю", "статус",
                }:
                    continue
                m = _AMOUNT_RE.search(nxt)
                if not m:
                    continue
                num = (
                    m.group(1)
                    .replace("\xa0", "")
                    .replace("\u202f", "")
                    .replace(" ", "")
                    .replace(",", ".")
                )
                try:
                    return float(num)
                except ValueError:
                    continue
    return None


def check_account_sbp_profile(
    pdf_bytes: bytes,
    text: str,
    *,
    producer: str = "",
    subtype: str = "",
) -> AccountSbpResult:
    out = AccountSbpResult()
    if subtype != SUBTYPE_SBP_ACCOUNT:
        return out

    pr = (producer or "").strip()
    out.stats["producer"] = pr
    if not pr.lower().startswith("openpdf 2."):
        out.flags.append(_flag(
            "VTB_ACCOUNT_SBP_PRODUCER_MISMATCH",
            f"Producer «{pr or '—'}» — у СБП на счёт ВТБ OpenPDF 2.0.x, "
            f"не openhtmltopdf и не чужой сериализатор",
        ))

    has_bold = b"Arial-BoldMT" in (pdf_bytes or b"")
    has_reg = re.search(rb"(?<!Bold)ArialMT", pdf_bytes or b"") is not None
    out.stats["arial_bold"] = has_bold
    out.stats["arial_regular"] = has_reg
    if not (has_bold and has_reg):
        out.flags.append(_flag(
            "VTB_ACCOUNT_SBP_FONT_MISMATCH",
            "нет пары subset Arial-BoldMT + ArialMT — штатный OpenPDF-чек ВТБ "
            "на счёт всегда на Arial, не SF Pro",
        ))

    hinted = 0
    orders = []
    for _raw, dec in find_streams(pdf_bytes or b""):
        if not (dec and len(dec) >= 12 and dec[:4] in (b"\x00\x01\x00\x00", b"OTTO")):
            continue
        order = _sfnt_tags(dec)
        if not order:
            continue
        orders.append(list(order))
        if all(tag in order for tag in _HINT):
            hinted += 1
    out.stats["sfnt_orders"] = orders
    out.stats["hinted_fonts"] = hinted
    if orders and hinted < 1:
        out.flags.append(_flag(
            "VTB_ACCOUNT_SBP_SFNT_MISMATCH",
            f"FontFile2 без cvt/fpgm/prep (order={orders[0]}) — "
            f"нативный Arial OpenPDF 2 держит hinting, SEQ часто снимает",
        ))

    height = _mediabox_height(pdf_bytes)
    out.stats["mediabox_height"] = height
    if height is not None and height < 700:
        out.flags.append(_flag(
            "VTB_ACCOUNT_SBP_PAGE_MISMATCH",
            f"MediaBox height={height:.1f} — СБП на счёт ВТБ A4 (~842), "
            f"openhtml «Исходящий перевод СБП» узкий ~450",
        ))

    credit = _labeled_amount(text, "сумма зачисления")
    fee = _labeled_amount(text, "сумма комиссии")
    total = _labeled_amount(text, "сумма")
    out.stats["amounts"] = {"credit": credit, "fee": fee, "total": total}
    if credit is not None and total is not None:
        fee_val = fee if fee is not None else 0.0
        if abs(round(credit + fee_val, 2) - round(total, 2)) > 0.02:
            out.flags.append(_flag(
                "VTB_ACCOUNT_SBP_AMOUNT_MISMATCH",
                "Сумма ≠ Сумма зачисления + Комиссия",
            ))
    return out
