# -*- coding: utf-8 -*-
"""Yandex Jasper/OpenPDF generator invariants (not size-atlas novelty).

Genuine receipts write PDF CreationDate as OpenPDF UTC ``D:YYYYMMDDHHmmssZ``
and keep YSText loca/maxp at the full-font 911-glyph short-loca layout.
SEQ kits rewrite CreationDate as a locale string and recompute Regular maxp.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from io import BytesIO

from .structure import find_streams

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

# OpenPDF 1.3.32 always serializes Info /CreationDate this way (n=5 genuines,
# 3 unique files). Human ``17.07.2026 21:08`` is a SEQ rewrite.
_CREATION_DATE_RE = re.compile(rb"/CreationDate\s*\(([^\\()]*)\)")
_NATIVE_PDF_DATE_RE = re.compile(rb"^D:\d{14}Z$")

# YSText-Regular/Medium on native Jasper: short loca for 911 glyphs.
# loca = (911+1)*2 = 1824. SEQ Regular in the caught kit recomputes to 915/1832.
_YSTEXT_NUMGLYPHS = 911
_YSTEXT_LOCA = 1824
_REGULAR_GLYF_MIN = 2000  # Medium glyf stays 590; Regular body is 4k+


@dataclass
class YandexFlag:
    code: str
    detail: str
    rule_id: str = ""


@dataclass
class YandexCheck:
    flags: list[YandexFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _creation_date_raw(pdf_bytes: bytes) -> bytes | None:
    m = _CREATION_DATE_RE.search(pdf_bytes or b"")
    return m.group(1) if m else None


def _ttf_metrics(ttf: bytes) -> dict | None:
    if not ttf or len(ttf) < 12:
        return None
    if TTFont is not None:
        try:
            tt = TTFont(BytesIO(ttf))
            glyf = len(tt.getTableData("glyf")) if "glyf" in tt else None
            loca = len(tt.getTableData("loca")) if "loca" in tt else None
            num = int(tt["maxp"].numGlyphs) if "maxp" in tt else None
            tt.close()
            return {"glyf": glyf, "loca": loca, "numGlyphs": num, "ff2": len(ttf)}
        except Exception:
            pass
    n_tables = struct.unpack(">H", ttf[4:6])[0]
    tables: dict[bytes, tuple[int, int]] = {}
    for i in range(n_tables):
        off = 12 + i * 16
        if off + 16 > len(ttf):
            break
        tag = ttf[off : off + 4]
        toff, tlen = struct.unpack(">II", ttf[off + 8 : off + 16])
        tables[tag] = (toff, tlen)
    loca = tables.get(b"loca", (0, 0))[1] or None
    glyf = tables.get(b"glyf", (0, 0))[1] or None
    maxp_off, maxp_len = tables.get(b"maxp", (0, 0))
    num = None
    if maxp_off and maxp_len >= 6 and maxp_off + 6 <= len(ttf):
        num = struct.unpack(">H", ttf[maxp_off + 4 : maxp_off + 6])[0]
    return {"glyf": glyf, "loca": loca, "numGlyphs": num, "ff2": len(ttf)}


def check_yandex_openpdf_invariants(pdf_bytes: bytes) -> YandexCheck:
    out = YandexCheck()
    raw = _creation_date_raw(pdf_bytes)
    out.stats["creation_date_raw"] = raw.decode("latin1", errors="replace") if raw else None
    if raw is None or not _NATIVE_PDF_DATE_RE.fullmatch(raw):
        shown = (raw or b"").decode("latin1", errors="replace") or "—"
        out.flags.append(YandexFlag(
            code="YANDEX_CREATION_DATE_FORMAT",
            detail=(
                f"/CreationDate({shown}) — OpenPDF Jasper пишет "
                f"D:YYYYMMDDHHmmssZ (UTC), не локальную строку"
            ),
            rule_id="K-YANDEX-CREATIONDATE-001",
        ))

    fonts = []
    for _obj, dec in find_streams(pdf_bytes or b""):
        if not dec or dec[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            continue
        met = _ttf_metrics(dec)
        if met:
            fonts.append(met)
    out.stats["ystext_fonts"] = fonts
    for met in fonts:
        glyf = met.get("glyf") or 0
        if glyf < _REGULAR_GLYF_MIN:
            continue
        num = met.get("numGlyphs")
        loca = met.get("loca")
        if num == _YSTEXT_NUMGLYPHS and loca == _YSTEXT_LOCA:
            continue
        out.flags.append(YandexFlag(
            code="YANDEX_YSTEXT_FULLFONT_METRICS",
            detail=(
                f"YSText-Regular maxp.numGlyphs={num} loca={loca} B "
                f"(нативный Jasper держит полный шрифт "
                f"{_YSTEXT_NUMGLYPHS}/{_YSTEXT_LOCA}; SEQ пересчитал subset)"
            ),
            rule_id="K-YANDEX-YSTEXT-MAXP-001",
        ))
    return out
