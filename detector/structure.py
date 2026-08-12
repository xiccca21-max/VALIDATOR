"""
Bank-agnostic PDF structural integrity checks (spec sections 1, 2, 15, 16, 29).
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

_STARTXREF_RE = re.compile(rb"startxref\s+(\d+)")
_XREF_ENTRY_RE = re.compile(rb"(\d{10}) (\d{5}) ([nf])")
_SUBSEC_RE = re.compile(rb"(\d+)\s+(\d+)\s*\r?\n")
_W_RE = re.compile(rb"/W\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]")
_SIZE_RE = re.compile(rb"/Size\s+(\d+)")
_INDEX_RE = re.compile(rb"/Index\s*\[([\d\s]+)\]")
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj")
_STREAM_LEN_RE = re.compile(rb"/Length\s+(\d+)")


@dataclass
class StructureFlags:
    codes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str) -> None:
        self.codes.append(code)
        self.details.append(detail)


_INT_OBJ_RE = re.compile(rb"(\d+)\s+0\s+obj\s+(\d+)\s+endobj")
_OBJ_BODY_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.DOTALL)
_STREAM_KW_RE = re.compile(rb">>\s*stream\r?\n")


def _indirect_lengths(pdf_bytes: bytes) -> dict[int, int]:
    return {int(m.group(1)): int(m.group(2)) for m in _INT_OBJ_RE.finditer(pdf_bytes)}


def _length_from_hdr(hdr: bytes, indirect: dict[int, int]) -> int | None:
    m = re.search(rb"/Length\s+(\d+)\s+0\s+R", hdr)
    if m:
        return indirect.get(int(m.group(1)))
    m = _STREAM_LEN_RE.search(hdr)
    return int(m.group(1)) if m else None


def _decompress_raw(raw: bytes) -> bytes:
    if not raw:
        return b""
    try:
        return zlib.decompress(raw)
    except Exception:
        return b""


def _stream_from_obj(obj: bytes, indirect: dict[int, int]) -> tuple[bytes, bytes]:
    """Извлечь (raw, decompressed) из одного PDF-объекта со stream."""
    sm = re.search(rb"stream\r?\n", obj)
    if not sm:
        return b"", b""
    hdr = obj[: sm.start()]
    start = sm.end()
    ln = _length_from_hdr(hdr, indirect)
    if ln and ln > 0:
        raw = obj[start : start + ln]
    else:
        em = obj.find(b"endstream", start)
        if em < 0:
            return b"", b""
        raw = obj[start:em].rstrip(b"\r\n")
    return raw, _decompress_raw(raw)


def find_streams(pdf_bytes: bytes):
    """Yield (raw_bytes, decompressed_bytes) для каждого stream-объекта PDF."""
    indirect = _indirect_lengths(pdf_bytes)
    seen: set[tuple[int, bytes]] = set()

    def _yield_unique(raw: bytes):
        if not raw:
            return
        key = (len(raw), raw[:16])
        if key in seen:
            return
        seen.add(key)
        return raw, _decompress_raw(raw)

    # Pass 1: объекты N M obj … stream (с /Length и косвенными ссылками)
    for m in _OBJ_BODY_RE.finditer(pdf_bytes):
        raw, dec = _stream_from_obj(m.group(0), indirect)
        if not raw:
            continue
        key = (len(raw), raw[:16])
        if key in seen:
            continue
        seen.add(key)
        yield raw, dec

    # Pass 2: >> stream … (для PDF с нестандартной разметкой объектов)
    for m in _STREAM_KW_RE.finditer(pdf_bytes):
        start = m.end()
        hdr = pdf_bytes[max(0, m.start() - 400) : m.start()]
        ln = _length_from_hdr(hdr, indirect)
        if ln and ln > 0:
            raw = pdf_bytes[start : start + ln]
        else:
            es = pdf_bytes.find(b"endstream", start)
            if es < 0:
                continue
            raw = pdf_bytes[start:es].rstrip(b"\r\n")
        key = (len(raw), raw[:16])
        if key in seen:
            continue
        seen.add(key)
        yield raw, _decompress_raw(raw)


def is_content_stream(dec: bytes) -> bool:
    if not dec or len(dec) < 200:
        return False
    return b"BT" in dec and (b"Tj" in dec or b"TJ" in dec) and b"Tm" in dec


def content_stream_bytes(pdf_bytes: bytes) -> bytes:
    """Самый большой текстовый content stream страницы."""
    best = b""
    for _, dec in find_streams(pdf_bytes):
        if not dec:
            continue
        if is_content_stream(dec) or (b"BT" in dec and (b"Tj" in dec or b"TJ" in dec)):
            if len(dec) > len(best):
                best = dec
    return best


def content_skeleton_hash(pdf_bytes: bytes) -> str | None:
    """Хэш «скелета» content stream без подставленного текста.

    Имена, суммы и прочий Tj/TJ-текст вырезаются — новый оригинал с другими
    буквами в том же шаблоне Jasper даёт тот же skeleton, что и эталоны.
    """
    import hashlib

    raw = content_stream_bytes(pdf_bytes)
    if not raw:
        return None
    sk = re.sub(rb"\([^)]*\)\s*Tj", b"() Tj", raw)
    sk = re.sub(rb"<[0-9A-Fa-f]*>\s*Tj", b"<> Tj", sk)
    sk = re.sub(rb"\d+\.?\d*\s+\d+\.?\d*\s+Td", b"N N Td", sk)
    return hashlib.sha256(sk).hexdigest()[:16]


def xref_integrity(pdf_bytes: bytes) -> tuple[bool, str]:
    """Returns (broken, detail). broken=True => inconsistent xref."""
    b = pdf_bytes
    sx = b.rfind(b"startxref")
    if sx < 0:
        return (True, "в файле нет startxref")

    m = _STARTXREF_RE.search(b, sx)
    if not m:
        return (True, "startxref без корректного смещения")
    off = int(m.group(1))
    if off <= 0 or off >= len(b):
        return (True, f"startxref={off} указывает за пределы файла")

    head = b[off:off + 24]
    if head[:4] == b"xref":
        return _validate_classic(b, off)
    if re.match(rb"\d+\s+\d+\s+obj", head):
        return _validate_xref_stream(b, off)
    return (True, "startxref не указывает на xref или xref-stream")


def _validate_classic(b: bytes, off: int) -> tuple[bool, str]:
    if b[off:off + 4] != b"xref":
        return (True, "ожидался xref")
    trailer = b.rfind(b"trailer")
    if trailer < 0:
        return (True, "нет trailer")
    body = b[off:trailer]
    for m in _XREF_ENTRY_RE.finditer(body):
        o = int(m.group(1))
        if m.group(3) == b"n" and o > 0:
            if o >= len(b):
                return (True, f"xref entry offset {o} за пределами файла")
            if not re.match(rb"\d+\s+\d+\s+obj", b[o:o + 32]):
                return (True, f"xref offset {o} не указывает на объект")
    return (False, "")


def _validate_xref_stream(b: bytes, off: int) -> tuple[bool, str]:
    try:
        om = re.match(rb"(\d+)\s+(\d+)\s+obj", b[off:off + 40])
        if not om:
            return (True, "некорректный xref-stream объект")
        objnum = int(om.group(1))
        stream_start = b.find(b"stream", off)
        if stream_start < 0:
            return (True, "xref-stream без stream")
        cs = stream_start + 6
        if b[cs:cs + 2] == b"\r\n":
            cs += 2
        elif b[cs:cs + 1] == b"\n":
            cs += 1
        es = b.find(b"endstream", cs)
        raw = b[cs:es].rstrip(b"\r\n")
        dec = zlib.decompress(raw)
        sm = _SIZE_RE.search(b[off:stream_start])
        if not sm:
            return (False, "")
        size = int(sm.group(1))
        wm = _W_RE.search(b[off:stream_start])
        if not wm:
            return (False, "")
        w = [int(wm.group(i)) for i in range(1, 4)]
        idx_m = _INDEX_RE.search(b[off:stream_start])
        if idx_m:
            parts = [int(x) for x in idx_m.group(1).split()]
            if len(parts) >= 2:
                first, count = parts[0], parts[1]
            else:
                first, count = 0, size
        else:
            first, count = 0, size
        row = w[0] + w[1] + w[2]
        need = count * row
        if len(dec) < need:
            return (True, "xref-stream слишком короткий")
        return (False, "")
    except Exception as e:
        return (True, f"ошибка разбора xref-stream: {e}")


def validate_pdf_structure(pdf_bytes: bytes) -> StructureFlags:
    """Section 1: primary PDF structure validation."""
    out = StructureFlags()
    b = pdf_bytes

    header_pos = b.find(b"%PDF-")
    if header_pos < 0:
        out.add("PDF_STRUCTURE_INVALID", "отсутствует корректный PDF-заголовок %PDF-")
    elif header_pos > 0 and b[:header_pos].strip(b"\x00\r\n \t"):
        out.add("PDF_STRUCTURE_INVALID", "перед PDF-заголовком есть непустые данные")
    if b.count(b"%PDF-") > 1:
        out.add("MULTIPLE_PDF_HEADERS", "в файле найдено несколько PDF-заголовков")

    ver = b[:8].decode("latin1", "replace").strip()
    out.stats["pdf_version"] = ver

    if b.count(b"trailer") < 1 and b"/Type /XRef" not in b and b"/Type/XRef" not in b:
        out.add("TRAILER_INVALID", "отсутствует trailer")

    if b.rfind(b"startxref") < 0:
        out.add("XREF_OFFSET_INVALID", "отсутствует startxref")
    elif b.count(b"startxref") > 1:
        out.add("MULTIPLE_STARTXREF_PRESENT", "в файле найдено несколько startxref")

    if b.rfind(b"%%EOF") < 0:
        out.add("PDF_STRUCTURE_INVALID", "отсутствует маркер %%EOF")

    obj_defs: dict[tuple[bytes, bytes], int] = {}
    duplicate_objects = 0
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj", b):
        key = (m.group(1), m.group(2))
        obj_defs[key] = obj_defs.get(key, 0) + 1
    duplicate_objects = sum(1 for n in obj_defs.values() if n > 1)
    if duplicate_objects:
        out.add(
            "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
            f"повторно определено {duplicate_objects} PDF-объект(ов)",
        )

    broken, detail = xref_integrity(b)
    if broken:
        out.add("XREF_OFFSET_INVALID", detail or "нарушена целостность xref")

    # stream /Length vs actual + decompression
    length_mismatches = 0
    decompress_failures = 0
    for raw, dec in find_streams(b):
        if raw[:2] == b"\x78":
            if not dec:
                decompress_failures += 1
    # scan objects for /Length declarations
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj(.*?)stream\r?\n", b, re.S):
        obj_hdr = m.group(3)
        lm = _STREAM_LEN_RE.search(obj_hdr)
        if not lm:
            continue
        declared = int(lm.group(1))
        stream_body_start = m.end()
        end = b.find(b"endstream", stream_body_start)
        if end < 0:
            out.add("BROKEN_OBJECT_STRUCTURE", "незакрытый stream-блок")
            continue
        actual = end - stream_body_start
        if actual != declared and abs(actual - declared) > 2:
            length_mismatches += 1

    if decompress_failures:
        out.add("STREAM_DECOMPRESSION_FAILED",
                 f"не удалось распаковать {decompress_failures} FlateDecode-поток(ов)")
    if length_mismatches:
        out.add("STREAM_LENGTH_MISMATCH",
                 f"/Length не совпадает с фактическим размером у {length_mismatches} поток(ов)")

    out.stats["stream_decompress_failures"] = decompress_failures
    out.stats["stream_length_mismatches"] = length_mismatches
    return out


def validate_incremental_updates(pdf_bytes: bytes) -> StructureFlags:
    """Section 2: incremental update markers."""
    out = StructureFlags()
    b = pdf_bytes

    eof_count = b.count(b"%%EOF")
    out.stats["eof_count"] = eof_count
    if eof_count > 1:
        out.add("MULTIPLE_EOF_PRESENT", f"обнаружено {eof_count} маркеров %%EOF")

    xref_count = len(re.findall(rb"\bxref\b", b))
    out.stats["xref_count"] = xref_count
    if xref_count > 1:
        out.add("MULTIPLE_XREF_PRESENT", f"обнаружено {xref_count} таблиц xref")

    if b"/Prev " in b or b"/Prev\n" in b:
        out.add("PREV_TRAILER_PRESENT", "в trailer есть /Prev — инкрементальное обновление")
        out.add("INCREMENTAL_UPDATE_PRESENT", "PDF содержит incremental update")

    last_eof = b.rfind(b"%%EOF")
    if last_eof >= 0 and last_eof + 5 < len(b.rstrip(b"\r\n \t")):
        tail = b[last_eof + 5:].strip()
        if tail:
            out.add(
                "TRAILING_DATA_AFTER_EOF",
                "после последнего %%EOF есть непустые данные",
            )

    return out


def validate_stream_compression(pdf_bytes: bytes) -> StructureFlags:
    """Sections 15–16: compression ratio and filter anomalies."""
    out = StructureFlags()
    ratios: list[float] = []
    headers: list[str] = []
    filters_seen: set[str] = set()

    for raw, dec in find_streams(pdf_bytes):
        if len(raw) >= 2:
            headers.append(raw[:2].hex())
        if raw:
            ratios.append(len(dec) / max(len(raw), 1))
        if b"/ASCIIHexDecode" in pdf_bytes[:5000]:
            filters_seen.add("ASCIIHexDecode")
        if b"/DCTDecode" in pdf_bytes:
            filters_seen.add("DCTDecode")
        if b"/JPXDecode" in pdf_bytes:
            filters_seen.add("JPXDecode")

    out.stats["zlib_headers"] = headers
    out.stats["compression_ratios"] = [round(r, 2) for r in ratios[:20]]

    if not headers and b"stream" in pdf_bytes:
        out.add("STREAM_FILTER_ANOMALY", "есть stream-объекты, но нет распознанного FlateDecode")

    unique_h = set(headers)
    if len(unique_h) > 1 and b"\x78\x9c" in [bytes.fromhex(h) for h in unique_h if len(h) == 4]:
        out.add("STREAM_COMPRESSION_RATIO_OUTLIER",
                 "смешанные уровни zlib-сжатия внутри одного PDF")

    for raw, dec in find_streams(pdf_bytes):
        if dec and is_content_stream(dec) and len(dec) > 20_000:
            out.add("DECODED_STREAM_SIZE_OUTLIER",
                     f"content stream аномально большой ({len(dec)} байт)")
            break

    unexpected = filters_seen - {"FlateDecode"}
    if unexpected:
        out.add("UNEXPECTED_STREAM_FILTER",
                 f"неожиданные фильтры: {', '.join(sorted(unexpected))}")

    return out


_JS_KEY_RE = re.compile(rb"/(?:JavaScript|JS)(?:\s|[\[(<])")
_AA_KEY_RE = re.compile(rb"/AA\s")


def validate_active_content(pdf_bytes: bytes) -> StructureFlags:
    """Sections 30–31: PDF capabilities and active content."""
    out = StructureFlags()
    b = pdf_bytes

    # Не путать с сабсет-префиксами шрифтов: /BaseFont/JSOLSA+ALSRubl, /FontName/JSHTAS+…
    if _JS_KEY_RE.search(b):
        out.add("JAVASCRIPT_PRESENT", "в PDF есть JavaScript")
        out.add("ACTIVE_CONTENT_PRESENT", "активное содержимое: JavaScript")

    if b"/EmbeddedFile" in b or b"/EmbeddedFiles" in b:
        out.add("EMBEDDED_FILE_PRESENT", "в PDF есть вложенные файлы")
        out.add("EMBEDDED_PAYLOAD_PRESENT", "вложенный payload")

    if b"/AcroForm" in b:
        out.add("ACROFORM_PRESENT", "в PDF есть AcroForm")

    if b"/XFA" in b:
        out.add("XFA_PRESENT", "в PDF есть XFA-формы")

    if b"/OpenAction" in b:
        out.add("OPENACTION_PRESENT", "в PDF есть OpenAction")
        out.add("DANGEROUS_ACTION_PRESENT", "действие при открытии PDF")

    if _AA_KEY_RE.search(b):
        out.add("DANGEROUS_ACTION_PRESENT", "дополнительные действия (/AA)")

    if b"/Launch" in b:
        out.add("DANGEROUS_ACTION_PRESENT", "оператор Launch")

    if b"/RichMedia" in b:
        out.add("ACTIVE_CONTENT_PRESENT", "RichMedia")

    annot_count = len(re.findall(rb"/Subtype\s*/Link", b))
    out.stats["link_annotations"] = annot_count

    return out
