"""
Deep PDF forensic validation (spec sections 3–14, 17–28, 32).

Returns machine-readable flags with weights for integration into bank detectors.
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from io import BytesIO

from .structure import find_streams, is_content_stream

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None


class Weight(IntEnum):
    HIGH = 95
    MEDIUM = 65
    LOW = 30


# T-Bank SBP receipt statistical profile (from genuine samples)
_TBANK_PROFILE = {
    "content_stream_min": 3000,
    "content_stream_max": 8000,
    "text_ops_count": 33,
    "bfrange_min": 30,
    "glyph_counts": {476, 479},
    "cid_density_max": 0.50,
    "unused_glyph_ratio_max": 0.48,
    "zlib_header": b"\x78\x9c",
    "head_checksum_adj": 863796543,
    "hmtx_hashes": {"f45b998da9da", "6957d7a5e820"},
    "units_per_em": 1000,
}

# Right-edge X tolerance for T-Bank SBP value column (from genuine cluster)
_RIGHT_EDGE_TOLERANCE = 8.0

_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_BF1_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BF2_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_TM_RE = re.compile(rb"1 0 0 1 (-?\d+\.\d+|-?\d+) (-?\d+\.\d+|-?\d+) Tm")
_TJ_RE = re.compile(rb"(\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f]+>)\s*TJ?")
_FONT_REF_RE = re.compile(rb"/([A-Za-z0-9]+)\s+(\d+)\s+0\s+R")
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj")


@dataclass
class ForensicFlag:
    code: str
    weight: Weight
    detail: str


@dataclass
class ForensicResult:
    flags: list[ForensicFlag] = field(default_factory=list)
    score: int = 0
    checks: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    template: str = "unknown"

    def add(self, code: str, weight: Weight, detail: str) -> None:
        self.flags.append(ForensicFlag(code, weight, detail))
        self.score += int(weight)

    def codes(self) -> list[str]:
        return [f.code for f in self.flags]


def _parse_W_arrays(pdf_bytes: bytes) -> dict[int, int]:
    """CID -> width from all /W arrays."""
    widths: dict[int, int] = {}
    for m in re.finditer(rb"/W\s*\[", pdf_bytes):
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, min(len(pdf_bytes), start + 12000)):
            c = pdf_bytes[i:i + 1]
            if c == b"[":
                depth += 1
            elif c == b"]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        arr = pdf_bytes[start:end]
        for mm in re.finditer(rb"(\d+)\s*\[([^\]]*)\]", arr):
            c0 = int(mm.group(1))
            nums = [int(x) for x in re.findall(rb"\d+", mm.group(2))]
            for k, w in enumerate(nums):
                widths[c0 + k] = w
        arr2 = re.sub(rb"\d+\s*\[[^\]]*\]", b" ", arr)
        for mm in re.finditer(rb"(\d+)\s+(\d+)\s+(\d+)", arr2):
            c1, c2, w = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
            for cid in range(c1, c2 + 1):
                widths[cid] = w
    return widths


def _cmap_blobs(pdf_bytes: bytes) -> list[bytes]:
    """Raw PDF plus decompressed streams that may contain CMap."""
    blobs = [pdf_bytes]
    for raw, dec in find_streams(pdf_bytes):
        if dec and (b"beginbfchar" in dec or b"beginbfrange" in dec):
            blobs.append(dec)
    return blobs


def _count_cmap_sections(pdf_bytes: bytes) -> tuple[int, int]:
    bfrange = bfchar = 0
    for blob in _cmap_blobs(pdf_bytes):
        bfrange += len(_BFRANGE_RE.findall(blob))
        bfchar += len(_BFCHAR_RE.findall(blob))
    return bfrange, bfchar


def _cmap_unicode(pdf_bytes: bytes) -> tuple[dict[int, str], set[str]]:
    """CID -> char and all chars from ToUnicode streams."""
    cid_map: dict[int, str] = {}
    for blob in _cmap_blobs(pdf_bytes):
        for m in _BFCHAR_RE.finditer(blob):
            for hm in _BF1_RE.finditer(m.group(1)):
                try:
                    cid = int(hm.group(1), 16)
                    u = bytes.fromhex(hm.group(2).decode()[:4]).decode("utf-16-be", "ignore")
                    if u:
                        cid_map[cid] = u
                except Exception:
                    pass
        for m in _BFRANGE_RE.finditer(blob):
            for hm in _BF2_RE.finditer(m.group(1)):
                try:
                    lo, hi = int(hm.group(1), 16), int(hm.group(2), 16)
                    base = int(hm.group(3).decode(), 16)
                    for i, cid in enumerate(range(lo, hi + 1)):
                        cid_map[cid] = chr(base + i)
                except Exception:
                    pass
    chars = set(cid_map.values())
    return cid_map, chars


def _used_cids_from_content(content: bytes) -> list[int]:
    """Extract CID sequence from Tj/TJ hex strings in content stream."""
    cids: list[int] = []
    for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*TJ?", content):
        hexs = m.group(1).decode()
        for i in range(0, len(hexs) - 3, 4):
            try:
                cids.append(int(hexs[i:i + 4], 16))
            except Exception:
                pass
    return cids


def _extract_font_programs(pdf_bytes: bytes) -> list[bytes]:
    fonts = []
    for raw, dec in find_streams(pdf_bytes):
        if dec[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf") and len(dec) > 500:
            fonts.append(dec)
    return fonts


def _ttf_tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    try:
        nt = int.from_bytes(data[4:6], "big")
        if nt <= 0 or nt > 64:
            return {}
        t = {}
        for i in range(nt):
            o = 12 + i * 16
            tag = data[o:o + 4]
            off = int.from_bytes(data[o + 8:o + 12], "big")
            ln = int.from_bytes(data[o + 12:o + 16], "big")
            t[tag] = (off, ln)
        return t
    except Exception:
        return {}


def _glyph_outline_hash(tt_data: bytes, gid: int) -> str | None:
    if TTFont is None:
        return None
    try:
        tt = TTFont(BytesIO(tt_data))
        order = tt.getGlyphOrder()
        if gid >= len(order):
            return None
        g = tt["glyf"][order[gid]]
        data = g.compile(tt["glyf"]) if hasattr(g, "compile") else b""
        return hashlib.sha1(data).hexdigest()[:12]
    except Exception:
        return None


def _parse_content_operators(content: bytes) -> dict:
    """Parse BT/ET blocks with Tm and text-show ops."""
    bt_count = content.count(b"BT")
    et_count = content.count(b"ET")
    blocks = []
    pos = 0
    while True:
        s = content.find(b"BT", pos)
        if s < 0:
            break
        e = content.find(b"ET", s)
        if e < 0:
            break
        block = content[s:e + 2]
        pos = e + 2
        x = y = 0.0
        texts = []
        font = None
        for line in block.split(b"\n"):
            if b"Tf" in line:
                m = re.search(rb"/([^\s]+)\s+[\d.]+\s+Tf", line)
                if m:
                    font = m.group(1).decode("latin1", "replace")
            tm = _TM_RE.search(line)
            if tm:
                x = float(tm.group(1))
                y = float(tm.group(2))
            tj = _TJ_RE.search(line)
            if tj:
                texts.append((x, y, font, tj.group(1)))
        if texts:
            blocks.append(texts)
    return {
        "bt": bt_count,
        "et": et_count,
        "blocks": blocks,
        "text_show_count": sum(len(b) for b in blocks),
    }


def _classify_tbank_template(text: str, content: bytes) -> str:
    flat = " ".join(text.split())
    if "Идентификатор операции" in flat and "Перевод" in flat:
        if "Сообщение" in flat or "сообщение" in flat:
            return "tbank_sbp_with_message"
        return "tbank_sbp"
    if "Перевод" in flat and "Получатель" in flat:
        return "tbank_transfer"
    if "Итого" in flat:
        return "tbank_short"
    return "unknown"


def run_pdf_forensics(
    pdf_bytes: bytes,
    *,
    bank: str = "tbank",
    tier: str | None = None,
    channel: str | None = None,
) -> ForensicResult:
    """Run deep forensic layers; tier selects which checks apply."""
    from .forensics_profile import forensics_tier, load_forensics_profile

    tier = tier or forensics_tier(bank)
    res = ForensicResult()
    profile = load_forensics_profile(bank, channel)
    layout_tier = tier in ("full", "jasper")
    cmap_tier = tier == "full"
    ttf_tier = tier == "full"
    template_tier = tier == "full"

    # ── 3. Object graph (lightweight) ───────────────────────────────────────
    obj_nums = {int(m.group(1)) for m in _OBJ_RE.finditer(pdf_bytes)}
    res.stats["object_count"] = len(obj_nums)
    if b"/Type /Page" not in pdf_bytes and b"/Type/Page" not in pdf_bytes:
        res.add("OBJECT_GRAPH_INCONSISTENT", Weight.HIGH, "нет объекта страницы /Type /Page")
    if b"/Font" not in pdf_bytes:
        if tier != "universal":
            res.add("MISSING_FONT_OBJECT", Weight.HIGH, "в Resources нет шрифтов /Font")
    if b"ToUnicode" not in pdf_bytes and tier == "full":
        res.add("MISSING_CMAP_OBJECT", Weight.MEDIUM, "нет ToUnicode CMap")
    if tier == "full" and b"/W [" not in pdf_bytes and b"/W[" not in pdf_bytes:
        res.add("MISSING_WIDTH_TABLE", Weight.HIGH, "нет таблицы ширин /W")

    # ── 4–5. Content stream & coordinates ───────────────────────────────────
    content = b""
    for _, dec in find_streams(pdf_bytes):
        if is_content_stream(dec):
            content = dec
            break

    if content:
        ops = _parse_content_operators(content)
        res.stats["content_ops"] = ops
        res.checks["content_stream"] = "ok"

        if ops["bt"] != ops["et"]:
            res.add("TEXT_OPERATOR_SEQUENCE_ANOMALY", Weight.MEDIUM,
                    f"несбалансированные BT/ET: {ops['bt']} vs {ops['et']}")
            res.add("CONTENT_STREAM_PROFILE_MISMATCH", Weight.MEDIUM,
                    "нарушена последовательность текстовых операторов")

        if bank == "tbank" and ops["text_show_count"] and ops["text_show_count"] != profile.get("text_ops_count", 33):
            if abs(ops["text_show_count"] - profile["text_ops_count"]) > 15:
                res.add("UNEXPECTED_TEXT_BLOCK_STRUCTURE", Weight.LOW,
                        f"аномальное число текстовых блоков: {ops['text_show_count']} "
                        f"(ожидалось ~{profile['text_ops_count']})")

        clen = len(content)
        res.stats["content_stream_size"] = clen
        cmin = profile.get("content_stream_min")
        cmax = profile.get("content_stream_max")
        if cmin is not None and cmax is not None and (clen < cmin or clen > cmax):
            res.add("CONTENT_STREAM_PROFILE_MISMATCH", Weight.LOW,
                    f"размер content stream {clen} вне профиля {cmin}–{cmax}")

        if layout_tier:
            # Right-edge alignment: value fields should share similar right edge
            widths = _parse_W_arrays(pdf_bytes)
            right_edges: list[float] = []
            for block in ops["blocks"]:
                for x, y, _font, tok in block:
                    if tok.startswith(b"<") and tok.endswith(b">"):
                        hexs = tok[1:-1].decode()
                        wsum = 0
                        for i in range(0, len(hexs) - 3, 4):
                            try:
                                cid = int(hexs[i:i + 4], 16)
                                wsum += widths.get(cid, 500)
                            except Exception:
                                pass
                        right_edges.append(x + wsum / 1000.0)

            if len(right_edges) >= 4:
                med = sorted(right_edges)[len(right_edges) // 2]
                outliers = [r for r in right_edges if abs(r - med) > _RIGHT_EDGE_TOLERANCE]
                res.stats["right_edges"] = [round(r, 1) for r in right_edges[:15]]
                if outliers:
                    res.add("RIGHT_EDGE_ALIGNMENT_DRIFT", Weight.MEDIUM,
                            f"{len(outliers)} текстовых строк с отклонением правого края "
                            f"> {_RIGHT_EDGE_TOLERANCE}pt от медианы")
                    res.add("LOCAL_ALIGNMENT_ANOMALY", Weight.MEDIUM,
                            "локальное смещение выравнивания одного или нескольких полей")

            # High-precision Tm (3+ decimals)
            bad_coords = []
            for xm, ym in _TM_RE.findall(content):
                for c in (xm, ym):
                    cs = c.decode()
                    if b"." in c and len(cs.split(".")[1]) >= 3:
                        bad_coords.append(cs)
            if bad_coords:
                res.add("FIELD_POSITION_OUT_OF_PROFILE", Weight.MEDIUM,
                        f"координаты Tm с избыточной точностью: {', '.join(bad_coords[:3])}")
                res.add("TM_NOT_RECALCULATED", Weight.MEDIUM,
                        "координаты пересчитаны с точностью, нехарактерной для JasperReports")
    else:
        res.checks["content_stream"] = "missing"

    # ── 7–9. CMap / W sync & serialization ──────────────────────────────────
    cid_map, cmap_chars = _cmap_unicode(pdf_bytes)
    wmap = _parse_W_arrays(pdf_bytes)
    used = set(_used_cids_from_content(content)) if content else set()

    res.stats["cmap_cids"] = len(cid_map)
    res.stats["w_cids"] = len(wmap)
    res.stats["used_cids"] = len(used)

    if cmap_tier and used:
        missing_cmap = used - set(cid_map)
        missing_w = used - set(wmap)
        if missing_cmap:
            res.add("USED_CID_MISSING_FROM_CMAP", Weight.HIGH,
                    f"{len(missing_cmap)} используемых CID отсутствуют в ToUnicode")
            res.add("CMAP_INVALID", Weight.HIGH, "CMap не покрывает используемые CID")
        if missing_w:
            res.add("USED_CID_MISSING_FROM_W", Weight.HIGH,
                    f"{len(missing_w)} используемых CID отсутствуют в /W")
        extra_w = set(wmap) - set(cid_map) if cid_map else set()
        if extra_w and len(extra_w) > 5:
            res.add("W_EXTRA_CID", Weight.MEDIUM,
                    f"{len(extra_w)} CID в /W без записи в CMap")
            res.add("CMAP_W_MISMATCH", Weight.HIGH, "рассинхрон CMap и /W")

    bfrange_count, bfchar_count = _count_cmap_sections(pdf_bytes)
    res.stats["bfrange_count"] = bfrange_count
    res.stats["bfchar_count"] = bfchar_count

    if cmap_tier and bfchar_count and not bfrange_count:
        res.add("CMAP_BFRANGE_ANOMALY", Weight.HIGH,
                "ToUnicode содержит только bfchar без bfrange — нехарактерно для OpenPDF")
        res.add("TOUNICODE_PROFILE_SHIFT", Weight.HIGH,
                "профиль ToUnicode смещён от банковского генератора")

    if bank == "tbank" and bfrange_count < profile.get("bfrange_min", 30) and len(wmap) > 50 and bfchar_count:
        res.add("TOUNICODE_PROFILE_SHIFT", Weight.MEDIUM,
                f"мало bfrange ({bfrange_count}), характерно для fontTools")

    # /W serialization style
    if cmap_tier:
        for m in re.finditer(rb"/W\s*\[", pdf_bytes):
            start = m.end() - 1
            depth = 0
            j = start
            while j < len(pdf_bytes):
                ch = pdf_bytes[j:j + 1]
                if ch == b"[":
                    depth += 1
                elif ch == b"]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            arr = pdf_bytes[start:j + 1]
            if re.search(rb"\d\s+\[", arr):
                res.add("W_ARRAY_SERIALIZATION_ANOMALY", Weight.HIGH,
                        "/W записан с пробелами — сторонняя сериализация")
                res.add("W_ARRAY_PRETTY_PRINTED", Weight.HIGH,
                        "массив /W отформатирован чужим инструментом")
                break

    # Orphan glyphs in CMap vs extracted text
    if cmap_tier and fitz and cmap_chars:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "".join(p.get_text() for p in doc)
            doc.close()
            text_chars = {c for c in text if c.isalpha() or c.isdigit()}
            orphans = {c for c in cmap_chars if c.isalpha()} - text_chars
            if len(orphans) > 3:
                res.add("UNUSED_CID_PRESENT", Weight.MEDIUM,
                        f"в CMap есть символы, не встречающиеся в тексте: "
                        f"«{''.join(sorted(orphans)[:8])}»")
                res.add("CMAP_EXTRA_SYMBOLS", Weight.MEDIUM,
                        "остатки символов шаблона в карте глифов")
        except Exception:
            pass

    # ── 10–12. FontFile2 / TTF tables / trailing padding ────────────────────
    fonts = _extract_font_programs(pdf_bytes)
    res.stats["embedded_fonts"] = len(fonts)

    if ttf_tier:
        for fdata in fonts:
            tables = _ttf_tables(fdata)
            if not tables:
                continue
            if b"maxp" in tables:
                ng = int.from_bytes(fdata[tables[b"maxp"][0] + 4:tables[b"maxp"][0] + 6], "big")
                res.stats.setdefault("glyph_counts", []).append(ng)
                if bank == "tbank" and ng > 100 and ng not in profile.get("glyph_counts", {}):
                    res.add("GLYPH_COUNT_OUTLIER", Weight.HIGH,
                            f"numGlyphs={ng}, ожидалось {sorted(profile['glyph_counts'])}")
                    res.add("TTF_MAXP_ANOMALY", Weight.MEDIUM, "аномальное число глифов в maxp")

            if b"head" in tables and b"maxp" in tables:
                ho = tables[b"head"][0]
                ng = int.from_bytes(fdata[tables[b"maxp"][0] + 4:tables[b"maxp"][0] + 6], "big")
                if ng > 200:
                    adj = int.from_bytes(fdata[ho + 8:ho + 12], "big")
                    upem = int.from_bytes(fdata[ho + 18:ho + 20], "big")
                    if upem and upem != profile.get("units_per_em", 1000):
                        res.add("BAD_UNITS_PER_EM", Weight.HIGH,
                                f"unitsPerEm={upem}, ожидалось {profile.get('units_per_em', 1000)}")
                    if bank == "tbank" and adj != profile.get("head_checksum_adj"):
                        res.add("TTF_HEAD_ANOMALY", Weight.HIGH,
                                f"head.checkSumAdjustment=0x{adj:08X} не совпадает с OpenPDF")
                        res.add("TTF_CHECKSUM_MISMATCH", Weight.MEDIUM,
                                "контрольная сумма head-таблицы не из профиля Т-Банка")

            if b"hmtx" in tables and b"maxp" in tables:
                ng = int.from_bytes(fdata[tables[b"maxp"][0] + 4:tables[b"maxp"][0] + 6], "big")
                if ng > 200:
                    ho, hl = tables[b"hmtx"]
                    hh = hashlib.md5(fdata[ho:ho + hl]).hexdigest()[:12]
                    if bank == "tbank" and hh not in profile.get("hmtx_hashes", {}):
                        res.add("TTF_HMTX_PROFILE_SHIFT", Weight.HIGH,
                                "hmtx не совпадает с эталоном OpenPDF/FontBox")

            if len(tables) >= 3:
                tags = list(tables.keys())
                ordered_offs = [tables[t][0] for t in sorted(tags)]
                if any(ordered_offs[i] >= ordered_offs[i + 1] for i in range(len(ordered_offs) - 1)):
                    res.add("TTF_TABLE_PROFILE_SHIFT", Weight.MEDIUM,
                            "таблицы TTF расположены не в каноническом порядке FontBox")

            if tables:
                last_end = max(off + ln for off, ln in tables.values())
                tail = len(fdata) - last_end
                res.stats.setdefault("font_tail_padding", []).append(tail)
                if tail > 64:
                    res.add("TTF_TRAILING_PADDING_OUTLIER", Weight.HIGH,
                            f"после последней TTF-таблицы {tail} байт padding")
                    res.add("FONT_LENGTH_PADDED_ARTIFICIALLY", Weight.MEDIUM,
                            "длина FontFile2 искусственно дополнена")

            break

        if fonts and len(fonts[0]) > 400_000:
            res.add("FONTFILE2_SIZE_OUTLIER", Weight.MEDIUM,
                    f"FontFile2 аномально большой ({len(fonts[0])} байт)")

        if fonts and used and TTFont:
            fdata = fonts[0]
            for cid in list(used)[:40]:
                h = _glyph_outline_hash(fdata, cid)
                if h is None and cid in cid_map and cid_map[cid].isdigit():
                    res.add("GLYPH_OUTLINE_MISMATCH", Weight.HIGH,
                            f"контур глифа CID {cid} ({cid_map.get(cid, '?')}) не читается")
                    break

    # ── 14. Font layer /W vs hmtx — отключено: OpenPDF /W не совпадает с hmtx на оригиналах

    # ── 17–18. Overlay & masking (conservative) ────────────────────────────────
    if content and tier == "full":
        # duplicate text at nearly same position
        positions = []
        for block in _parse_content_operators(content)["blocks"]:
            for x, y, _f, _t in block:
                positions.append((round(x, 1), round(y, 1)))
        dup = len(positions) - len(set(positions))
        if dup > 10:
            res.add("TEXT_DRAWN_TWICE", Weight.LOW,
                    f"повторный вывод текста в одной области ({dup} совпадений)")
            res.add("OVERLAY_TEXT_LAYER", Weight.MEDIUM,
                    "признак наложенного текстового слоя")

        # white masking rectangle near text zone (y 150–450 typical for SBP body)
        if re.search(rb"1\s+1\s+1\s+rg.*\d+\s+\d+\s+\d+\s+-\d+\s+re\s+f", content):
            res.add("MASKING_RECTANGLE_PRESENT", Weight.LOW,
                    "белый заливающий прямоугольник в content stream")
            res.add("MASKING_GRAPHICS_NEAR_TEXT", Weight.LOW,
                    "графическая маска рядом с текстовой зоной")

    # ── 19–22. Template, field order, local anomalies ───────────────────────
    if template_tier and fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "".join(p.get_text() for p in doc)
            doc.close()
            res.template = _classify_tbank_template(text, content)
            res.stats["template"] = res.template

            if res.template == "unknown" and bank == "tbank":
                res.add("UNKNOWN_TEMPLATE", Weight.MEDIUM,
                        "не удалось классифицировать шаблон квитанции")
                res.add("TEMPLATE_CLASSIFICATION_FAILED", Weight.MEDIUM,
                        "шаблон не соответствует известным профилям Т-Банк СБП")

            # Required blocks for SBP
            if res.template.startswith("tbank_sbp"):
                required = ["Итого", "Статус", "Отправитель", "Получатель", "Идентификатор"]
                missing = [r for r in required if r not in text]
                if missing:
                    res.add("MISSING_REQUIRED_FIELD_BLOCK", Weight.MEDIUM,
                            f"отсутствуют блоки: {', '.join(missing)}")
                    res.add("FIELD_SET_MISMATCH", Weight.MEDIUM,
                            "набор полей не соответствует шаблону СБП")

                # Field order: labels should appear in canonical order
                positions = [(label, text.find(label)) for label in required if label in text]
                positions.sort(key=lambda x: x[1])
                order = [p[0] for p in positions]
                if order != required[:len(order)] and len(order) >= 3:
                    res.add("FIELD_ORDER_MISMATCH", Weight.MEDIUM,
                            f"порядок полей {order} не совпадает с шаблоном")

            # Field format (structure only, not values)
            flat = text.replace("\n", " ")
            if "Идентификатор" in text:
                opid_m = re.search(r"[AB]\d{2}[A-Z0-9]{29}", flat.replace(" ", ""))
                if not opid_m:
                    res.add("FIELD_FORMAT_INVALID", Weight.MEDIUM,
                            "идентификатор операции не соответствует структуре 32 символов")
                    res.add("STRING_FIELD_STRUCTURE_ANOMALY", Weight.MEDIUM,
                            "структура поля идентификатора нарушена")

            # Сумма: Jasper/OpenPDF часто без копеек в текстовом слое — не используем как сигнал

        except Exception:
            res.checks["text_layer"] = "error"

    # ── 23. Text layer consistency ──────────────────────────────────────────
    if fitz and content:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            extracted = "".join(p.get_text() for p in doc)
            doc.close()
            if "Итого" in extracted and len(extracted.strip()) < 80:
                res.add("TEXT_LAYER_INCONSISTENT", Weight.HIGH,
                        "извлечённый текст слишком короткий для квитанции")
                res.add("TEXT_EXTRACTION_MAPPING_ANOMALY", Weight.HIGH,
                        "текстовый слой не согласован с визуальным содержимым")
            if "\ufffd" in extracted or "(cid:" in extracted.lower():
                res.add("UNICODE_MAPPING_INVALID", Weight.HIGH,
                        "битые символы при извлечении текста")
                res.add("BROKEN_CYRILLIC_MAPPING", Weight.MEDIUM,
                        "нарушено отображение кириллицы в текстовом слое")
        except Exception:
            pass

    # ── 26. FontDescriptor ────────────────────────────────────────────────────
    if tier == "full":
        bbox_m = re.findall(rb"/FontBBox\s*\[([^\]]+)\]", pdf_bytes)
        if bbox_m and not fonts:
            res.add("FONTFILE_DESCRIPTOR_INCONSISTENT", Weight.MEDIUM,
                    "есть FontDescriptor, но нет FontFile2")
            res.add("FONTFILE2_MISSING", Weight.HIGH, "отсутствует встроенный FontFile2")

    # ── 27. Page resources ──────────────────────────────────────────────────
    # Font references in content should exist in page resources — heuristic
    font_names_page = set(re.findall(rb"/BaseFont\s*/([^\s/\]]+)", pdf_bytes))
    res.stats["font_names"] = [f.decode("latin1", "replace") for f in list(font_names_page)[:10]]
    if content and b"Tf" in content and not font_names_page:
        res.add("PAGE_RESOURCES_INCONSISTENT", Weight.MEDIUM,
                "в content stream есть Tf, но шрифты не найдены в Resources")
        res.add("RESOURCE_REFERENCE_BROKEN", Weight.MEDIUM,
                "битая ссылка на ресурс шрифта")

    # ── 28. XObject ─────────────────────────────────────────────────────────
    xobj_count = len(re.findall(rb"/Type\s*/XObject", pdf_bytes))
    res.stats["xobject_count"] = xobj_count
    if xobj_count > 8:
        res.add("XOBJECT_PROFILE_SHIFT", Weight.LOW,
                f"необычно много XObject ({xobj_count}) для текстовой квитанции")
    if b"/Subtype /Image" in pdf_bytes and content and tier == "full":
        # image + heavy text overlay in same receipt can be patch marker
        if b"Do" in content:
            res.add("RASTER_OVERLAY_PRESENT", Weight.MEDIUM,
                    "растровое изображение отрисовывается поверх страницы")

    # ── 29. Object streams ──────────────────────────────────────────────────
    if b"/Type /ObjStm" in pdf_bytes or b"/Type/ObjStm" in pdf_bytes:
        res.add("OBJECT_STREAM_PRESENT", Weight.LOW,
                "PDF использует object streams (PDF 1.5+) — нехарактерно для старых Jasper PDF")

    # ── 32. Statistical profile cluster ─────────────────────────────────────
    weak = 0
    if res.stats.get("content_stream_size"):
        sz = res.stats["content_stream_size"]
        cmin = profile.get("content_stream_min")
        cmax = profile.get("content_stream_max")
        if cmin is not None and cmax is not None and (sz < cmin or sz > cmax):
            weak += 1
    if res.stats.get("bfrange_count", 0) < 20:
        weak += 1
    if res.stats.get("used_cids") and res.stats.get("w_cids"):
        density = res.stats["used_cids"] / max(res.stats.get("w_cids", 1), 1)
        if density > 0.85:
            weak += 1
            res.add("CID_SEQUENCE_ANOMALY", Weight.MEDIUM,
                    f"высокая плотность CID ({density:.2f}) — перенумерация глифов")
    if weak >= 2:
        res.add("MULTIPLE_WEAK_ANOMALIES", Weight.LOW,
                "несколько слабых статистических отклонений от профиля")
        res.add("PROFILE_CLUSTER_OUTLIER", Weight.MEDIUM,
                "документ выбивается из кластера оригинальных квитанций")

    # Risk bucket (spec §33)
    if res.score <= 20:
        res.checks["risk_bucket"] = "LOW_RISK"
    elif res.score <= 50:
        res.checks["risk_bucket"] = "MEDIUM_RISK"
    else:
        res.checks["risk_bucket"] = "HIGH_RISK"

    return res


def forensics_to_log_dict(result: ForensicResult) -> dict:
    """Format for internal logs (spec §35)."""
    return {
        "template": result.template,
        "score": result.score,
        "risk_bucket": result.checks.get("risk_bucket"),
        "flags": result.codes(),
        "flag_details": [{"code": f.code, "weight": int(f.weight), "detail": f.detail}
                         for f in result.flags],
        "stats": result.stats,
        "checks": result.checks,
    }
