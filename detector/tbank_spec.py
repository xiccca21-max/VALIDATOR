"""
Проверки Т-Банка по формуле chadgpt-plus (v0.4.0).

ОРИГИНАЛ — нет жёстких нарушений из 10 категорий.
ФЕЙК — только по: shell, producer, active content, fonts, CID, glyph,
font tables, overlay, amounts, layout-family.

Запрещено банить по: одиночный F1 SHA, rare_letters, file_size, «новый ToUnicode».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    detect_receipt_channel,
    detect_receipt_subtype,
    receipt_subtype_label,
)
from .font_layers import _font_objects, extract_amounts_from_text
from .pdf_forensics import (
    ForensicResult,
    Weight,
    _cmap_unicode,
    _parse_W_arrays,
    _ttf_tables,
    _used_cids_from_content,
)
from .structure import find_streams, is_content_stream

# ── §2 Foreign Producer ───────────────────────────────────────────────────────
FOREIGN_PRODUCER_MARKERS = (
    "reportlab",
    "pikepdf",
    "pypdf",
    "acrobat",
    "itext",
    "pdf-lib",
    "pdf_lib",
    "libreoffice",
    "canva",
    "ilovepdf",
    "smallpdf",
    "pdfedit",
    "pdfium",
    "chromium",
    "skia/pdf",
    "skia",
    "cairo",
    "ghostscript",
    "quartz pdfcontext",
)

# ── §3 Active content ─────────────────────────────────────────────────────────
ACTIVE_CONTENT_CODES = frozenset({
    "JAVASCRIPT_PRESENT",
    "ACTIVE_CONTENT_PRESENT",
    "OPENACTION_PRESENT",
    "DANGEROUS_ACTION_PRESENT",
    "EMBEDDED_FILE_PRESENT",
    "EMBEDDED_PAYLOAD_PRESENT",
    "ACROFORM_PRESENT",
    "XFA_PRESENT",
})

# ── §10 Layout-family (порядок блоков в чеке) ─────────────────────────────────
LAYOUT_FAMILY = (
    "Дата",
    "Итого",
    "Перевод",
    "Статус",
    "Сумма",
    "Комиссия",
    "Отправитель",
    "Телефон",
    "Получатель",
    "Банк",
    "Счет",
    "СБП",
    "Поддержка",
    "Квитанция",
)

_LAYOUT_ALIASES: dict[str, tuple[str, ...]] = {
    "Дата": ("Дата",),
    "Итого": ("Итого",),
    "Перевод": ("Перевод",),
    "Статус": ("Статус",),
    "Сумма": ("Сумма",),
    "Комиссия": ("Комиссия",),
    "Отправитель": ("Отправитель",),
    "Телефон": ("Телефон получателя", "Телефон"),
    "Получатель": ("Получатель", "Карта получателя"),
    "Банк": ("Банк получателя", "Банк"),
    "Счет": ("Счет списания", "Счет"),
    "СБП": ("Идентификатор операции", "СБП"),
    "Поддержка": ("Поддержка", "fb@tbank.ru", "Служба поддержки"),
    "Квитанция": ("Квитанция",),
}

# Ядро layout-family — порядок обязателен
_LAYOUT_CORE = (
    "Дата",
    "Итого",
    "Перевод",
    "Статус",
    "Сумма",
    "Отправитель",
    "Получатель",
)

_LAYOUT_OPTIONAL = frozenset({
    "Комиссия", "Телефон", "Банк", "Счет", "СБП", "Квитанция",
})

_OBJ_HDR = re.compile(rb"(\d+)\s+0\s+obj")
_FONT_RES = re.compile(rb"/(F\d+)\s+(\d+)\s+0\s+R")


@dataclass
class SpecFlag:
    code: str
    detail: str


@dataclass
class SpecResult:
    flags: list[SpecFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str) -> None:
        self.flags.append(SpecFlag(code, detail))


def _extract_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _producer_creator(pdf_bytes: bytes) -> tuple[str, str]:
    if not fitz:
        return "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = doc.metadata or {}
        doc.close()
        return (meta.get("producer") or "", meta.get("creator") or "")
    except Exception:
        return "", ""


def check_foreign_producer(pdf_bytes: bytes) -> SpecResult:
    """§2 — сторонний Producer/Creator."""
    res = SpecResult()
    producer, creator = _producer_creator(pdf_bytes)
    res.stats["producer"] = producer
    res.stats["creator"] = creator
    combined = f"{producer} {creator}".lower()
    for marker in FOREIGN_PRODUCER_MARKERS:
        if marker in combined:
            res.add(
                "FOREIGN_PRODUCER",
                f"сторонний инструмент PDF: «{marker}» в Producer/Creator",
            )
            break
    return res


def check_required_fonts(pdf_bytes: bytes) -> SpecResult:
    """§4 — обязательные F1/F2/F3, F3 = ALSRubl."""
    res = SpecResult()
    fonts, _ = _font_objects(pdf_bytes)
    res.stats["font_keys"] = sorted(fonts.keys())
    for key in ("F1", "F2", "F3"):
        if key not in fonts:
            res.add("MISSING_REQUIRED_FONT", f"отсутствует обязательный шрифт {key}")
    f3 = fonts.get("F3", {})
    base = (f3.get("base_font") or "").upper()
    if "F3" in fonts and "ALSRUBL" not in base:
        res.add(
            "F3_NOT_ALSRUBL",
            f"шрифт F3 должен быть ALSRubl, найден: {f3.get('base_font', '?')}",
        )
    return res


def _extract_fontfile2_map(pdf_bytes: bytes) -> dict[str, bytes]:
    spans: dict[int, bytes] = {}
    for m in _OBJ_HDR.finditer(pdf_bytes):
        num = int(m.group(1))
        end = pdf_bytes.find(b"endobj", m.start())
        if end > 0:
            spans[num] = pdf_bytes[m.start():end]

    out: dict[str, bytes] = {}
    for font_key, num in {m.group(1).decode(): int(m.group(2))
                          for m in _FONT_RES.finditer(pdf_bytes)}.items():
        if num not in spans:
            continue
        blob = spans[num]
        dnum = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
        if dnum:
            blob = spans.get(int(dnum.group(1)), blob)
        fd = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", blob)
        if not fd:
            continue
        fd_blob = spans.get(int(fd.group(1)), b"")
        ff2 = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", fd_blob)
        if not ff2:
            continue
        ff2obj = spans.get(int(ff2.group(1)), b"")
        pos = ff2obj.find(b"stream")
        if pos < 0:
            continue
        cs = pos + 6
        if ff2obj[cs:cs + 2] == b"\r\n":
            cs += 2
        elif ff2obj[cs:cs + 1] == b"\n":
            cs += 1
        es = ff2obj.find(b"endstream", cs)
        raw = ff2obj[cs:es].rstrip(b"\r\n")
        if b"/FlateDecode" in ff2obj[:pos]:
            import zlib
            try:
                raw = zlib.decompress(raw)
            except Exception:
                continue
        out[font_key] = raw
    return out


def check_fontfile2_cid_integrity(pdf_bytes: bytes, content: bytes) -> SpecResult:
    """§5 — used_cid ∉ FontFile2 (глиф отсутствует в встроенном TTF)."""
    res = SpecResult()
    if not content or TTFont is None:
        return res

    cid_map, _ = _cmap_unicode(pdf_bytes)
    used = _used_cids_from_content(content)
    ff2_map = _extract_fontfile2_map(pdf_bytes)
    font_res, _ = _font_objects(pdf_bytes)

    missing: list[str] = []
    for font_key in ("F1", "F2", "F3"):
        ttf_data = ff2_map.get(font_key)
        if not ttf_data:
            continue
        try:
            tt = TTFont(BytesIO(ttf_data))
            order = tt.getGlyphOrder()
            ng = len(order)
            font_cids = {cid for cid in used if cid in (font_res.get(font_key, {}).get("cmap") or {})}
            if not font_cids:
                # Привязка CID к шрифту по content stream Tf
                continue
            for cid in used:
                if cid not in cid_map:
                    continue
                if cid >= ng:
                    missing.append(f"{font_key}:CID{cid}>numGlyphs{ng}")
        except Exception:
            continue

    # Проверка по каждому шрифту через used CIDs из font_layers runs — упрощённо:
    # все used CID должны иметь валидный глиф в соответствующем FontFile2
    for font_key, ttf_data in ff2_map.items():
        try:
            tt = TTFont(BytesIO(ttf_data))
            glyf = tt.get("glyf")
            order = tt.getGlyphOrder()
            cmap_font = font_res.get(font_key, {}).get("cmap") or {}
            for cid in used:
                if cid not in cmap_font:
                    continue
                if cid >= len(order):
                    missing.append(f"{font_key}:CID{cid} вне FontFile2")
                    continue
                gname = order[cid]
                g = glyf[gname]
                if g.numberOfContours == 0 and gname != ".notdef":
                    res.add(
                        "BROKEN_GLYPH_ZERO_LENGTH",
                        f"нулевой контур глифа CID {cid} ({gname}) в {font_key}",
                    )
                    return res
        except Exception:
            continue

    if missing:
        res.add(
            "FONTFILE2_CID_MISSING",
            f"используемые CID отсутствуют во FontFile2: {', '.join(missing[:5])}",
        )
    return res


def check_glyph_and_font_tables(pdf_bytes: bytes) -> SpecResult:
    """§6–7 — glyph integrity и font table consistency."""
    res = SpecResult()
    if TTFont is None:
        return res

    ff2_map = _extract_fontfile2_map(pdf_bytes)
    for font_key, ttf_data in ff2_map.items():
        try:
            tt = TTFont(BytesIO(ttf_data))
            tables = _ttf_tables(ttf_data)
            order = tt.getGlyphOrder()
            actual = len(order)
            ng = actual
            if b"maxp" in tables:
                off = tables[b"maxp"][0]
                ng = int.from_bytes(ttf_data[off + 4:off + 6], "big")
                if ng != actual:
                    res.add(
                        "TTF_NUMGLYPHS_MISMATCH",
                        f"{font_key}: numGlyphs={ng} ≠ фактических {actual}",
                    )

            if b"loca" in tables and b"glyf" in tables:
                loca = tt["loca"]
                glyf = tt["glyf"]
                for i, gname in enumerate(order):
                    try:
                        g = glyf[gname]
                        if g.numberOfContours > 0:
                            if g.xMax < g.xMin or g.yMax < g.yMin:
                                res.add(
                                    "GLYPH_BBOX_IMPOSSIBLE",
                                    f"{font_key}: невозможный bbox у глифа {gname}",
                                )
                                return res
                    except Exception:
                        res.add(
                            "LOCA_TABLE_BROKEN",
                            f"{font_key}: повреждена таблица loca для глифа #{i}",
                        )
                        return res

            # checkSumAdjustment — только полный TTF (F1/F2 ~476/479 глифов), не subset
            if b"head" in tables and ng > 200:
                ho = tables[b"head"][0]
                adj = int.from_bytes(ttf_data[ho + 8:ho + 12], "big")
                if font_key == "F1" and adj != 863796543:
                    res.add(
                        "TTF_CHECKSUM_ADJUSTMENT_INVALID",
                        f"{font_key}: head.checkSumAdjustment=0x{adj:08X} невалиден",
                    )

            if b"hmtx" in tables and ng > 200:
                ho, hl = tables[b"hmtx"]
                expected_len = ng * 4
                if expected_len and hl < expected_len - 4:
                    res.add(
                        "TTF_HMTX_COUNT_MISMATCH",
                        f"{font_key}: hmtx короче ожидаемого для {ng} глифов",
                    )
        except Exception:
            continue
    return res


def _find_layout_positions(text: str) -> list[tuple[str, int]]:
    positions: list[tuple[str, int]] = []
    m = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
    if m:
        positions.append(("Дата", m.start()))
    for label in LAYOUT_FAMILY:
        if label == "Дата":
            continue
        for alias in _LAYOUT_ALIASES.get(label, (label,)):
            if alias.startswith("fb@"):
                idx = text.find(alias)
            else:
                idx = text.find(alias)
            if idx >= 0:
                positions.append((label, idx))
                break
    # «Карта получателя» → блок Получатель (шаблон «На карту»)
    if "Получатель" not in {p[0] for p in positions}:
        km = text.find("Карта получателя")
        if km >= 0:
            positions.append(("Получатель", km))
    if "Квитанция" not in {p[0] for p in positions}:
        km = re.search(r"Квитанция\s*№", text)
        if km:
            positions.append(("Квитанция", km.start()))
    return positions


def check_layout_family(text: str, channel: str, subtype: str = "") -> SpecResult:
    """§10 — порядок блоков layout-family (ядро строго, хвост гибко)."""
    res = SpecResult()
    if not text or "Итого" not in text:
        return res

    positions = _find_layout_positions(text)
    if len(positions) < 5:
        return res

    present = {p[0] for p in positions}
    core_required = list(_LAYOUT_CORE)
    # Шаблон «На карту» — нет поля «Получатель», есть «Карта получателя»
    if subtype == "card_transfer" or (
        channel == CHANNEL_CARD and "Карта получателя" in text
    ):
        core_required = [c for c in core_required if c != "Получатель"]
        if "Карта получателя" in text:
            present.add("Получатель")

    core_missing = [c for c in core_required if c not in present]
    if core_missing:
        res.add(
            "LAYOUT_FAMILY_MISSING",
            f"отсутствуют обязательные блоки: {', '.join(core_missing)}",
        )

    if channel == CHANNEL_SBP and "СБП" not in present:
        # Достаточно «Идентификатор операции»
        if "Идентификатор операции" not in text:
            res.add("LAYOUT_FAMILY_MISSING", "отсутствует блок СБП / Идентификатор операции")

    # Строгий порядок только для ядра
    pos_map = {label: idx for label, idx in positions}
    core_present = [c for c in core_required if c in pos_map]
    for i in range(len(core_present) - 1):
        a, b = core_present[i], core_present[i + 1]
        if pos_map[a] > pos_map[b]:
            ordered = sorted(
                [(l, pos_map[l]) for l in core_present], key=lambda x: x[1],
            )
            res.add(
                "LAYOUT_FAMILY_VIOLATION",
                f"нарушен порядок ядра: {[x[0] for x in ordered]} "
                f"(ожидается {_LAYOUT_CORE})",
            )
            break

    res.stats["layout_labels"] = [p[0] for p in sorted(positions, key=lambda x: x[1])]
    return res


def check_amount_integrity(text: str) -> SpecResult:
    """§9 — Итого vs Сумма (+ Комиссия)."""
    res = SpecResult()
    amounts = extract_amounts_from_text(text)
    res.stats["amounts"] = amounts
    top = amounts.get("top")
    details = amounts.get("details")
    comm = amounts.get("commission") or 0
    if top is None or details is None:
        return res
    if top != details:
        if not (comm > 0 and top == details + comm):
            res.add(
                "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS",
                f"Итого {top} ≠ Сумма {details}"
                + (f" (+ комиссия {comm})" if comm else ""),
            )
    return res


def check_overlay_text_layer(pdf_bytes: bytes, content: bytes) -> SpecResult:
    """§8 — overlay attack: текст закрывает текст / визуальный ≠ текстовый слой."""
    res = SpecResult()
    if not content or not fitz:
        return res

    # Дублирование текста в одной позиции
    positions: list[tuple[float, float]] = []
    tm_re = re.compile(rb"1 0 0 1 (-?\d+\.?\d*) (-?\d+\.?\d*) Tm")
    for m in tm_re.finditer(content):
        positions.append((round(float(m.group(1)), 1), round(float(m.group(2)), 1)))
    if positions:
        dup = len(positions) - len(set(positions))
        if dup > 8:
            res.add(
                "OVERLAY_DETECTED",
                f"наложенный текстовый слой: {dup} повторных позиций Tm",
            )

    # Визуальный слой ≠ текстовый
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        extracted = "".join(p.get_text() for p in doc)
        doc.close()
        if "Итого" in extracted and len(extracted.strip()) < 80:
            res.add(
                "TEXT_LAYER_INCONSISTENT",
                "визуальный слой не согласован с извлечённым текстом",
            )
        if "\ufffd" in extracted or "(cid:" in extracted.lower():
            res.add(
                "TEXT_LAYER_INCONSISTENT",
                "битое отображение текста — признак overlay/подмены",
            )
    except Exception:
        pass

    # Белая маска поверх текста
    if re.search(rb"1\s+1\s+1\s+rg.*\d+\s+\d+\s+\d+\s+-\d+\s+re\s+f", content):
        res.add(
            "OVERLAY_DETECTED",
            "белый заливающий прямоугольник поверх текста (masking)",
        )

    return res


def run_tbank_spec_checks(pdf_bytes: bytes) -> SpecResult:
    """Запуск всех проверок по формуле chadgpt-plus."""
    out = SpecResult()

    content = b""
    for _, dec in find_streams(pdf_bytes):
        if is_content_stream(dec):
            content = dec
            break

    text = _extract_text(pdf_bytes)
    channel = detect_receipt_channel(text)
    subtype = detect_receipt_subtype(text)
    out.stats["channel"] = channel
    out.stats["subtype"] = subtype
    out.stats["subtype_label"] = receipt_subtype_label(subtype)

    for part in (
        check_foreign_producer(pdf_bytes),
        check_required_fonts(pdf_bytes),
        check_fontfile2_cid_integrity(pdf_bytes, content),
        check_glyph_and_font_tables(pdf_bytes),
        check_layout_family(text, channel, subtype),
        check_amount_integrity(text),
        check_overlay_text_layer(pdf_bytes, content),
    ):
        out.flags.extend(part.flags)
        out.stats.update(part.stats)

    # CID ↔ ToUnicode ↔ /W — в pdf_forensics / font_layers
    return out
    """Конвертация в ForensicResult для единого pipeline."""
    fr = ForensicResult()
    fr.stats.update(result.stats)
    for f in result.flags:
        fr.add(f.code, Weight.HIGH, f.detail)
    return fr


def spec_to_log_dict(result: SpecResult) -> dict:
    return {
        "flags": [{"code": f.code, "detail": f.detail} for f in result.flags],
        "stats": result.stats,
    }
