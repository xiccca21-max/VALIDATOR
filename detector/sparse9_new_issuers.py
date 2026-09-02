# -*- coding: utf-8 -*-
"""Generator invariants for sparse issuers with n=1–2 genuines.

Not a glyf atlas. HARD laws are producer/creator, branded fonts, page box,
native PDF CreationDate, and issuer footer/BIK. File size is never pinned.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from io import BytesIO

from .structure import find_streams

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

_CREATION_DATE_RE = re.compile(rb"/CreationDate\s*\(([^\\()]*)\)")
_NATIVE_PDF_DATE_RE = re.compile(rb"^D:\d{14}(Z|[+\-]\d{2}'\d{2}')$")
_MEDIA_RE = re.compile(
    rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]"
)


@dataclass
class IssuerFlag:
    code: str
    detail: str
    rule_id: str = ""


@dataclass
class IssuerCheck:
    flags: list[IssuerFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _add(out: IssuerCheck, code: str, detail: str, rule_id: str = "") -> None:
    out.flags.append(IssuerFlag(code, detail, rule_id=rule_id or code))


def _creation_date_raw(pdf_bytes: bytes) -> bytes | None:
    m = _CREATION_DATE_RE.search(pdf_bytes or b"")
    return m.group(1) if m else None


def _ttf_metrics(ttf: bytes) -> dict | None:
    if not ttf or len(ttf) < 12:
        return None
    hinted = False
    tags: list[str] = []
    if TTFont is not None:
        try:
            tt = TTFont(BytesIO(ttf))
            tags = [t for t in tt.keys() if t not in ("GlyphOrder",)]
            hinted = all(t in tt for t in ("cvt ", "fpgm", "prep"))
            glyf = len(tt.getTableData("glyf")) if "glyf" in tt else None
            loca = len(tt.getTableData("loca")) if "loca" in tt else None
            num = int(tt["maxp"].numGlyphs) if "maxp" in tt else None
            tt.close()
            return {
                "glyf": glyf, "loca": loca, "numGlyphs": num,
                "ff2": len(ttf), "hinted": hinted, "tags": tags,
            }
        except Exception:
            pass
    n_tables = struct.unpack(">H", ttf[4:6])[0]
    tables: dict[bytes, tuple[int, int]] = {}
    for i in range(n_tables):
        off = 12 + i * 16
        if off + 16 > len(ttf):
            break
        tag = ttf[off:off + 4]
        toff, tlen = struct.unpack(">II", ttf[off + 8:off + 16])
        tables[tag] = (toff, tlen)
        tags.append(tag.decode("latin1", "replace"))
    hinted = all(t in tables for t in (b"cvt ", b"fpgm", b"prep"))
    loca = tables.get(b"loca", (0, 0))[1] or None
    glyf = tables.get(b"glyf", (0, 0))[1] or None
    maxp_off, maxp_len = tables.get(b"maxp", (0, 0))
    num = None
    if maxp_off and maxp_len >= 6 and maxp_off + 6 <= len(ttf):
        num = struct.unpack(">H", ttf[maxp_off + 4:maxp_off + 6])[0]
    return {
        "glyf": glyf, "loca": loca, "numGlyphs": num,
        "ff2": len(ttf), "hinted": hinted, "tags": tags,
    }


def _has_token(pdf_bytes: bytes, token: bytes) -> bool:
    if token in (pdf_bytes or b""):
        return True
    for _obj, dec in find_streams(pdf_bytes or b""):
        if dec and token in dec:
            return True
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            names = " ".join(
                (font[3] or "") for page in doc for font in page.get_fonts()
            )
            doc.close()
            needle = token.decode("ascii", "replace")
            if needle in names:
                return True
        except Exception:
            pass
    return False


def _embedded_fonts(pdf_bytes: bytes) -> list[dict]:
    out: list[dict] = []
    for _obj, dec in find_streams(pdf_bytes or b""):
        if not dec or dec[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            continue
        met = _ttf_metrics(dec)
        if met:
            out.append(met)
    return out


def _page_wh(pdf_bytes: bytes) -> tuple[float, float] | None:
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            rect = doc[0].rect
            doc.close()
            return float(rect.width), float(rect.height)
        except Exception:
            pass
    m = _MEDIA_RE.search(pdf_bytes or b"")
    if not m:
        return None
    x0, y0, x1, y1 = (float(g) for g in m.groups())
    return abs(x1 - x0), abs(y1 - y0)


def _check_native_creation_date(pdf_bytes: bytes, out: IssuerCheck, code: str, rule_id: str) -> None:
    raw = _creation_date_raw(pdf_bytes)
    shown = (raw or b"").decode("latin1", errors="replace") or "—"
    out.stats["creation_date_raw"] = shown
    if raw is None or not _NATIVE_PDF_DATE_RE.fullmatch(raw):
        _add(
            out, code,
            f"/CreationDate({shown}) — нативный генератор пишет PDF-дату "
            f"D:YYYYMMDDHHmmssZ или с часовым поясом, не локальную строку",
            rule_id,
        )


def _need_labels(text: str, labels: tuple[str, ...]) -> list[str]:
    low = (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()
    return [lab for lab in labels if lab not in low]


def check_mts_invariants(
    pdf_bytes: bytes, *, producer: str = "", creator: str = "", text: str = "",
) -> IssuerCheck:
    """МТС Деньги: dbo-print-forms + OpenPDF jaspersoft + MTSSans subset pair."""
    out = IssuerCheck()
    pr = (producer or "").lower()
    cr = (creator or "").strip()
    blob = pdf_bytes or b""
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    if "openpdf" not in pr or "jaspersoft" not in pr:
        _add(
            out, "MTS_PRODUCER_MISMATCH",
            f"Producer «{producer or '—'}» — МТС Деньги пишет OpenPDF … jaspersoft",
            "K-MTS-PRODUCER-001",
        )
    if cr.lower() != "dbo-print-forms":
        _add(
            out, "MTS_PRODUCER_MISMATCH",
            f"Creator «{creator or '—'}» ≠ dbo-print-forms",
            "K-MTS-CREATOR-001",
        )

    if not _has_token(blob, b"MTSSans-Regular") or not _has_token(blob, b"MTSSans-Medium"):
        _add(
            out, "MTS_FONT_MISMATCH",
            "нет пары MTSSans-Regular / MTSSans-Medium",
            "K-MTS-FONT-001",
        )
    fonts = _embedded_fonts(blob)
    out.stats["fonts"] = fonts
    unhinted = [f for f in fonts if not f.get("hinted")]
    nums = {f.get("numGlyphs") for f in unhinted if f.get("numGlyphs")}
    if unhinted and len(nums) > 1:
        _add(
            out, "MTS_FONT_MISMATCH",
            f"MTSSans Regular/Medium должны делить один subset cmap, numGlyphs={sorted(nums)}",
            "K-MTS-FONT-002",
        )
    if any(f.get("hinted") for f in fonts):
        _add(
            out, "MTS_FONT_MISMATCH",
            "MTSSans на dbo-print-forms — subset без cvt/fpgm/prep, не полный hinted TTF",
            "K-MTS-FONT-003",
        )

    wh = _page_wh(blob)
    out.stats["page_wh"] = wh
    if wh is None or not (350 <= wh[0] <= 400 and 690 <= wh[1] <= 750):
        shown = f"{wh[0]:.0f}×{wh[1]:.0f}" if wh else "—"
        _add(
            out, "MTS_PAGE_MISMATCH",
            f"страница {shown} — чек МТС Деньги ~375×720, не A4",
            "K-MTS-PAGE-001",
        )

    _check_native_creation_date(
        blob, out, "MTS_CREATION_DATE_FORMAT", "K-MTS-CREATIONDATE-001",
    )
    missing = _need_labels(text, (
        "счет списания", "код транзакции", "код операции сбп", "итого",
    ))
    if missing:
        _add(
            out, "MTS_FIELDSET_MISMATCH",
            "нет полей: " + ", ".join(missing),
            "K-MTS-FIELDS-001",
        )
    return out


def check_yoomoney_invariants(
    pdf_bytes: bytes, *, producer: str = "", creator: str = "", text: str = "",
) -> IssuerCheck:
    """ЮMoney card: iText 2.1.7 + Jasper 6.12 + FactorIO (not Sber 6.18)."""
    out = IssuerCheck()
    pr = (producer or "").lower()
    cr = (creator or "").lower()
    blob = pdf_bytes or b""
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    if "itext 2.1.7" not in pr:
        _add(
            out, "YOOMONEY_PRODUCER_MISMATCH",
            f"Producer «{producer or '—'}» — ЮMoney пишет iText 2.1.7",
            "K-YOOMONEY-PRODUCER-001",
        )
    if "jasperreports library version 6.12" not in cr:
        _add(
            out, "YOOMONEY_PRODUCER_MISMATCH",
            f"Creator «{creator or '—'}» — ЮMoney Jasper 6.12.1, не 6.18 Сбера",
            "K-YOOMONEY-CREATOR-001",
        )
    if not _has_token(blob, b"FactorIO-Regular") or not _has_token(blob, b"FactorIO-Bold"):
        _add(
            out, "YOOMONEY_FONT_MISMATCH",
            "нет пары FactorIO-Regular / FactorIO-Bold",
            "K-YOOMONEY-FONT-001",
        )
    fonts = _embedded_fonts(blob)
    out.stats["fonts"] = fonts
    unhinted = [f for f in fonts if not f.get("hinted")]
    nums = {f.get("numGlyphs") for f in unhinted if f.get("numGlyphs")}
    if unhinted and len(nums) > 1:
        _add(
            out, "YOOMONEY_FONT_MISMATCH",
            f"FactorIO Regular/Bold должны делить subset cmap, numGlyphs={sorted(nums)}",
            "K-YOOMONEY-FONT-002",
        )

    wh = _page_wh(blob)
    out.stats["page_wh"] = wh
    if wh is None or not (540 <= wh[0] <= 580 and 680 <= wh[1] <= 750):
        shown = f"{wh[0]:.0f}×{wh[1]:.0f}" if wh else "—"
        _add(
            out, "YOOMONEY_PAGE_MISMATCH",
            f"страница {shown} — чек ЮMoney ~560×713",
            "K-YOOMONEY-PAGE-001",
        )

    _check_native_creation_date(
        blob, out, "YOOMONEY_CREATION_DATE_FORMAT", "K-YOOMONEY-CREATIONDATE-001",
    )
    missing = _need_labels(text, (
        "номер кошелька", "перевод завершен", "идентификатор операции",
    ))
    if missing:
        _add(
            out, "YOOMONEY_FIELDSET_MISMATCH",
            "нет полей: " + ", ".join(missing),
            "K-YOOMONEY-FIELDS-001",
        )
    return out


def check_rsbank_invariants(
    pdf_bytes: bytes, *, producer: str = "", creator: str = "", text: str = "",
) -> IssuerCheck:
    """Русский Стандарт СБП: OpenPDF + short Creator JasperReports + Calibri/Times."""
    out = IssuerCheck()
    pr = (producer or "").lower()
    cr = (creator or "").strip()
    blob = pdf_bytes or b""
    low = (text or "").replace("\xa0", " ").lower()
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    if "openpdf" not in pr:
        _add(
            out, "RSBANK_PRODUCER_MISMATCH",
            f"Producer «{producer or '—'}» — Русский Стандарт пишет OpenPDF",
            "K-RSBANK-PRODUCER-001",
        )
    cr_l = cr.lower()
    if cr_l != "jasperreports":
        _add(
            out, "RSBANK_PRODUCER_MISMATCH",
            f"Creator «{creator or '—'}» — нативный RS пишет короткое «JasperReports», "
            f"не Library version",
            "K-RSBANK-CREATOR-001",
        )
    if not _has_token(blob, b"Calibri") or not _has_token(blob, b"TimesNewRoman"):
        _add(
            out, "RSBANK_FONT_MISMATCH",
            "нет пары Calibri / TimesNewRoman",
            "K-RSBANK-FONT-001",
        )
    fonts = _embedded_fonts(blob)
    out.stats["fonts"] = fonts
    if fonts and not all(f.get("hinted") for f in fonts):
        _add(
            out, "RSBANK_FONT_MISMATCH",
            "Calibri/Times на RS — полные hinted TTF (cvt/fpgm/prep), не subset",
            "K-RSBANK-FONT-002",
        )

    wh = _page_wh(blob)
    out.stats["page_wh"] = wh
    if wh is None or not (580 <= wh[0] <= 620 and 820 <= wh[1] <= 860):
        shown = f"{wh[0]:.0f}×{wh[1]:.0f}" if wh else "—"
        _add(
            out, "RSBANK_PAGE_MISMATCH",
            f"страница {shown} — чек Русского Стандарта A4 ~595×842",
            "K-RSBANK-PAGE-001",
        )

    _check_native_creation_date(
        blob, out, "RSBANK_CREATION_DATE_FORMAT", "K-RSBANK-CREATIONDATE-001",
    )
    if "044525151" not in (text or "").replace(" ", ""):
        _add(
            out, "RSBANK_ISSUER_BIK_MISMATCH",
            "нет БИК 044525151 эмитента АО «Русский Стандарт»",
            "K-RSBANK-BIK-001",
        )
    missing = _need_labels(text, (
        "чек операции", "перевод по сбп", "банк в кармане",
        "номер операции в сбп",
    ))
    if missing:
        _add(
            out, "RSBANK_FIELDSET_MISMATCH",
            "нет полей: " + ", ".join(missing),
            "K-RSBANK-FIELDS-001",
        )
    if "исполнено" not in low:
        _add(
            out, "RSBANK_FIELDSET_MISMATCH",
            "нет статуса ИСПОЛНЕНО",
            "K-RSBANK-STATUS-001",
        )
    return out


def check_tochka_invariants(
    pdf_bytes: bytes, *, producer: str = "", creator: str = "", text: str = "",
) -> IssuerCheck:
    """Точка СБП: OpenPDF + Jasper 6.21 + TTNormsTochka (not Yandex YSText)."""
    out = IssuerCheck()
    pr = (producer or "").lower()
    cr = (creator or "").lower()
    blob = pdf_bytes or b""
    low = (text or "").replace("\xa0", " ").lower()
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    if "openpdf" not in pr:
        _add(
            out, "TOCHKA_PRODUCER_MISMATCH",
            f"Producer «{producer or '—'}» — Точка пишет OpenPDF",
            "K-TOCHKA-PRODUCER-001",
        )
    if "jasperreports library version 6.21" not in cr:
        _add(
            out, "TOCHKA_PRODUCER_MISMATCH",
            f"Creator «{creator or '—'}» — нативная Точка Jasper 6.21.4",
            "K-TOCHKA-CREATOR-001",
        )
    if not _has_token(blob, b"TTNormsTochka"):
        _add(
            out, "TOCHKA_FONT_MISMATCH",
            "нет TTNormsTochka — шрифт эмитента Точки, не YSText Яндекса",
            "K-TOCHKA-FONT-001",
        )

    wh = _page_wh(blob)
    out.stats["page_wh"] = wh
    if wh is None or not (470 <= min(wh) <= 530 and 740 <= max(wh) <= 810):
        shown = f"{wh[0]:.0f}×{wh[1]:.0f}" if wh else "—"
        _add(
            out, "TOCHKA_PAGE_MISMATCH",
            f"страница {shown} — чек Точки ~500×774",
            "K-TOCHKA-PAGE-001",
        )

    _check_native_creation_date(
        blob, out, "TOCHKA_CREATION_DATE_FORMAT", "K-TOCHKA-CREATIONDATE-001",
    )
    compact = (text or "").replace(" ", "")
    if "044525104" not in compact:
        _add(
            out, "TOCHKA_ISSUER_BIK_MISMATCH",
            "нет БИК 044525104 эмитента ООО «Банк Точка»",
            "K-TOCHKA-BIK-001",
        )
    if "банк точка" not in low:
        _add(
            out, "TOCHKA_FIELDSET_MISMATCH",
            "нет подписи эмитента «Банк Точка»",
            "K-TOCHKA-ISSUER-001",
        )
    missing = _need_labels(text, (
        "исходящий перевод через сбп", "оплачено",
    ))
    if missing:
        _add(
            out, "TOCHKA_FIELDSET_MISMATCH",
            "нет полей: " + ", ".join(missing),
            "K-TOCHKA-FIELDS-001",
        )
    return out
