"""
Проверки Альфа-Банка по той же философии, что Т-Банк (chadgpt-plus),
но под Oracle BI Publisher — без FontFile2 / glyf / Jasper.

ОРИГИНАЛ — нет жёстких нарушений.
ФЕЙК — shell, foreign producer, active content, stream/images, amounts, layout, SBP-ID.

Не баним по: размер файла в одиночку, subset-префикс шрифта, >> stream у Oracle BI.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

try:
    import fitz
except ImportError:
    fitz = None

from .alfa_invariants import envelope_for_channel, global_content_envelope, in_envelope, load
from .ff2_pool import extract_fontfile2_streams
from .alfa_sbp_cipher import validate_alfa_sbp_cipher
from .alfa_profiles import (
    ALFA_FOREIGN_PRODUCERS,
    ALFA_IMAGE_SIZES,
    ALFA_NATIVE_PRODUCERS,
    CHANNEL_CARD,
    CHANNEL_SBP,
    detect_alfa_channel,
    detect_alfa_subtype,
    extract_bank_operation_id,
    extract_sbp_opid,
    receipt_subtype_label,
)
from .structure import find_streams, is_content_stream

# Ядро layout — только общие поля любого чека Альфы.
# Подтипы (СБП, телефон, карта межбанк/внутрибанк) не требуют полного списка блоков.
_LAYOUT_CORE = (
    "Сумма перевода",
    "Номер операции",
)

_LAYOUT_ALIASES: dict[str, tuple[str, ...]] = {
    "Сумма перевода": ("Сумма перевода",),
    "Номер операции": ("Номер операции", "Номер операции в банке"),
    "СБП": ("Идентификатор операции в СБП", "Идентификатор операции"),
}

_SBP_ID_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_AMOUNT_LINE_RE = re.compile(
    r"(\d[\d \u00a0]*)\s*(?:RUR|RUB|руб)",
    re.IGNORECASE,
)


@dataclass
class AlfaFlag:
    code: str
    detail: str


@dataclass
class AlfaSpecResult:
    flags: list[AlfaFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str) -> None:
        self.flags.append(AlfaFlag(code, detail))


def _extract_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = doc[0].get_text()
        doc.close()
        return text
    except Exception:
        return ""


def _meta(pdf_bytes: bytes) -> tuple[str, str]:
    if not fitz:
        return "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        m = doc.metadata or {}
        doc.close()
        return (m.get("producer") or "", m.get("creator") or "")
    except Exception:
        return "", ""


def check_foreign_producer(pdf_bytes: bytes, producer: str, creator: str) -> AlfaSpecResult:
    res = AlfaSpecResult()
    combined = f"{producer} {creator}".lower()
    res.stats["producer"] = producer
    res.stats["creator"] = creator

    if not any(p in combined for p in ALFA_NATIVE_PRODUCERS):
        if producer:
            res.add(
                "ALFA_PRODUCER_MISMATCH",
                f"Producer «{producer}» — не Oracle BI Publisher",
            )
        else:
            res.add("ALFA_PRODUCER_MISMATCH", "отсутствует Producer Oracle BI Publisher")

    for marker in ALFA_FOREIGN_PRODUCERS:
        if marker in combined:
            res.add(
                "FOREIGN_PRODUCER",
                f"сторонний PDF-генератор «{marker}» (ожидается Oracle BI Publisher)",
            )
            break
    return res


def check_oracle_bi_fonts(pdf_bytes: bytes) -> AlfaSpecResult:
    """Tahoma CIDFontType2 — как у всех оригиналов Oracle BI."""
    res = AlfaSpecResult()
    if b"+Tahoma" not in pdf_bytes and b"/Tahoma" not in pdf_bytes:
        res.add(
            "ALFA_MISSING_TAHOMA",
            "не найден шрифт Tahoma — обязателен для квитанций Альфа-Банка",
        )
    if b"jasperreports" in pdf_bytes.lower() or b"TinkoffSans" in pdf_bytes:
        res.add(
            "ALFA_JASPER_CLONE",
            "обнаружен Jasper/TinkoffSans — типичная подделка «под Альфу»",
        )
    return res


def _image_sizes(pdf_bytes: bytes) -> set[tuple[int, int]]:
    sizes: set[tuple[int, int]] = set()
    for m in re.finditer(rb"/Type\s*/XObject\s*/Subtype\s*/Image", pdf_bytes):
        chunk = pdf_bytes[m.start(): m.start() + 400]
        wm = re.search(rb"/Width\s+(\d+)", chunk)
        hm = re.search(rb"/Height\s+(\d+)", chunk)
        if wm and hm:
            sizes.add((int(wm.group(1)), int(hm.group(1))))
    return sizes


def check_images_and_content(pdf_bytes: bytes) -> AlfaSpecResult:
    res = AlfaSpecResult()
    imgs = _image_sizes(pdf_bytes)
    res.stats["image_sizes"] = sorted(imgs)

    if imgs != ALFA_IMAGE_SIZES:
        res.add(
            "ALFA_IMAGE_LAYOUT_MISMATCH",
            f"растровые блоки {sorted(imgs)} ≠ эталон {sorted(ALFA_IMAGE_SIZES)}",
        )

    content = b""
    raw_best = b""
    for raw, dec in find_streams(pdf_bytes):
        if dec and is_content_stream(dec):
            if len(dec) > len(content):
                content, raw_best = dec, raw
    res.stats["content_decoded"] = len(content) if content else 0

    if not content:
        res.add(
            "ALFA_CONTENT_STREAM_MISSING",
            "текстовый content stream не найден или не распаковывается",
        )
        return res

    if raw_best:
        try:
            zlib.decompress(raw_best)
        except Exception as e:
            res.add(
                "STREAM_DECOMPRESSION_FAILED",
                f"content stream повреждён: {e}",
            )

    if b"/Im0 Do" not in content or b"/Im1 Do" not in content:
        res.add(
            "ALFA_CONTENT_PREFIX_MISMATCH",
            "content stream без обязательных /Im0 Do и /Im1 Do",
        )
    if b".494" not in content:
        res.add(
            "ALFA_TEXT_COLOR_MISMATCH",
            "нет фирменного серого цвета текста (.494 RG)",
        )

    ops = content.count(b"BT"), content.count(b"ET")
    if ops[0] != ops[1]:
        res.add(
            "TEXT_OPERATOR_SEQUENCE_ANOMALY",
            f"несбалансированные BT/ET: {ops[0]} vs {ops[1]}",
        )

    tail_pad = len(content) - len(content.rstrip(b" \t\r\n\x0c"))
    last_et = content.rfind(b"ET")
    after_last_et = content[last_et + 2:] if last_et >= 0 else b""
    if tail_pad > 8 or (b"%" in after_last_et) or tail_pad not in (0, 2):
        res.add(
            "ALFA_CONTENT_STREAM_TAIL_PADDING",
            f"content stream заканчивается не как Oracle BI (tail padding {tail_pad} байт)",
        )
    return res


def _parse_amounts(text: str) -> dict:
    lines = [_norm_text(l).strip() for l in text.splitlines()]
    out: dict = {}
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("сумма перевода") or low == "сумма перевода":
            v = _next_val(lines, i)
            if v:
                m = _AMOUNT_LINE_RE.search(v)
                if m:
                    out["amount"] = int(re.sub(r"\D", "", m.group(1)) or "0")
        if low.startswith("комиссия"):
            v = _next_val(lines, i)
            if v:
                m = _AMOUNT_LINE_RE.search(v)
                if m:
                    out["commission"] = int(re.sub(r"\D", "", m.group(1)) or "0")
    return out


def _next_val(lines: list[str], i: int) -> str | None:
    rest = lines[i].split(":", 1)
    if len(rest) > 1 and rest[1].strip():
        return rest[1].strip()
    for j in range(i + 1, min(i + 4, len(lines))):
        if lines[j].strip():
            return lines[j].strip()
    return None


def check_amounts(text: str) -> AlfaSpecResult:
    res = AlfaSpecResult()
    amounts = _parse_amounts(text)
    res.stats["amounts"] = amounts
    if "amount" not in amounts:
        res.add("ALFA_AMOUNT_MISSING", "не найдена «Сумма перевода»")
    if "commission" in amounts and amounts["commission"] not in (0, amounts.get("amount")):
        # комиссия > 0 допустима, но должна быть согласована с полями
        pass
    return res


def _norm_text(text: str) -> str:
    return (text or "").replace("\xa0", " ")


def _find_layout_positions(text: str) -> list[tuple[str, int]]:
    norm = _norm_text(text)
    positions: list[tuple[str, int]] = []
    m = re.search(r"\d{2}\.\d{2}\.\d{4}", norm)
    if m:
        positions.append(("Дата", m.start()))
    for label in _LAYOUT_CORE:
        for alias in _LAYOUT_ALIASES.get(label, (label,)):
            idx = norm.find(alias)
            if idx >= 0:
                positions.append((label, idx))
                break
    return positions


def check_layout_family(text: str, channel: str) -> AlfaSpecResult:
    """Мягкая проверка: только ядро, без жёсткого списка полей подтипа."""
    res = AlfaSpecResult()
    norm = _norm_text(text)
    if not norm:
        return res

    positions = _find_layout_positions(norm)
    present = {p[0] for p in positions}
    core_missing = [c for c in _LAYOUT_CORE if c not in present]
    if core_missing:
        res.add(
            "LAYOUT_FAMILY_MISSING",
            f"отсутствуют обязательные блоки: {', '.join(core_missing)}",
        )

    if channel == CHANNEL_SBP:
        has_sbp = any(
            norm.find(a) >= 0
            for a in _LAYOUT_ALIASES.get("СБП", ())
        )
        if not has_sbp and not extract_sbp_opid(norm):
            res.add(
                "LAYOUT_FAMILY_MISSING",
                "отсутствует блок СБП / идентификатор операции",
            )

    res.stats["layout_labels"] = [p[0] for p in sorted(positions, key=lambda x: x[1])]
    return res


def check_sbp_opid(text: str, channel: str) -> AlfaSpecResult:
    res = AlfaSpecResult()
    if channel != CHANNEL_SBP:
        return res
    opid = extract_sbp_opid(text)
    res.stats["sbp_opid"] = opid
    if not opid:
        res.add("ALFA_SBP_ID_MISSING", "не найден идентификатор операции в СБП (32 символа)")
        return res

    cipher = validate_alfa_sbp_cipher(opid, text)
    res.stats["sbp_cipher"] = cipher.stats
    seen: set[str] = set()
    for cf in cipher.flags:
        if cf.code in seen:
            continue
        seen.add(cf.code)
        res.add(cf.code, cf.detail)

    bank_op = extract_bank_operation_id(text, channel)
    res.stats["bank_operation_id"] = bank_op
    if bank_op and not re.match(r"^C\d{15}$", bank_op):
        res.add(
            "ALFA_BANK_OP_ID_STRUCTURE",
            f"номер операции «{bank_op}» не соответствует формату C + 15 цифр",
        )
    return res


_DATE_TRANSFER_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_Z_OP_RE = re.compile(r"Z\d{15}")


def check_card_operation_id(text: str, channel: str) -> AlfaSpecResult:
    """Z09 + DDMMYY в номере операции карточного перевода должен совпадать с датой перевода."""
    res = AlfaSpecResult()
    if channel != CHANNEL_CARD:
        return res
    flat = re.sub(r"\s+", "", text or "")
    m = _Z_OP_RE.search(flat)
    if not m:
        return res
    op = m.group(0)
    if len(op) < 9:
        return res
    enc = op[3:9]
    norm = _norm_text(text)
    dates = list(_DATE_TRANSFER_RE.finditer(norm))
    if not dates:
        return res
    dm = dates[-1]
    d, mo, y = dm.group(1), dm.group(2), dm.group(3)[-2:]
    expected = f"{d}{mo}{y}"
    res.stats["bank_operation_id"] = op
    if enc != expected:
        res.add(
            "ALFA_OPERATION_ID_MISMATCH",
            f"в номере операции {op} зашита дата {enc[0:2]}.{enc[2:4]}.20{enc[4:6]}, "
            f"а дата перевода {dm.group(1)}.{dm.group(2)}.{dm.group(3)}",
        )
    return res


def check_envelope(pdf_bytes: bytes, text: str, channel: str) -> AlfaSpecResult:
    """Корпусные min/max; для нового подтипа — объединённый envelope всех каналов."""
    res = AlfaSpecResult()
    inv = load()
    ch_data = envelope_for_channel(channel)

    obj_count = len(re.findall(rb"\d+ 0 obj", pdf_bytes))
    res.stats["object_count"] = obj_count
    shell_obj = inv.get("shell", {}).get("object_count")
    if shell_obj and not in_envelope(obj_count, shell_obj):
        res.add(
            "ALFA_OBJECT_COUNT_OUTLIER",
            f"число PDF-объектов {obj_count} вне эталона {shell_obj}",
        )

    dec = res.stats.get("content_decoded") or 0
    if not dec:
        for _, d in find_streams(pdf_bytes):
            if d and is_content_stream(d):
                dec = max(dec, len(d))
    bounds = ch_data.get("content_decoded") or global_content_envelope()
    if bounds and dec:
        if not in_envelope(dec, bounds):
            lo, hi = bounds
            res.add(
                "ALFA_CONTENT_STREAM_OUTLIER",
                f"размер content stream {dec} вне корпуса оригиналов ({lo}–{hi})",
            )
    return res


def check_fontfile2_profile(pdf_bytes: bytes, channel: str) -> AlfaSpecResult:
    """Oracle BI embeds one Tahoma FontFile2 subset; compare only per channel."""
    res = AlfaSpecResult()
    ch_data = envelope_for_channel(channel)
    ff2 = extract_fontfile2_streams(pdf_bytes)
    res.stats["fontfile2_profile"] = {
        "count": len(ff2),
        "fonts": [
            {
                "sha256_16": x.get("sha256_16"),
                "size": x.get("size"),
                "font_name": x.get("font_name"),
            }
            for x in ff2
        ],
    }

    expected_count = ch_data.get("fontfile2_count")
    if expected_count and not in_envelope(len(ff2), expected_count):
        res.add(
            "ALFA_FONTFILE2_COUNT_OUTLIER",
            f"FontFile2 слоёв {len(ff2)} вместо эталона канала {channel} {expected_count}",
        )

    expected_size = ch_data.get("fontfile2_size")
    if expected_size and ff2:
        for font in ff2:
            size = int(font.get("size") or 0)
            if not in_envelope(size, expected_size):
                res.add(
                    "ALFA_FONTFILE2_SIZE_OUTLIER",
                    f"FontFile2 {size} B вне эталона канала {channel} {expected_size}",
                )
                break

    expected_names = set(ch_data.get("fontfile2_names") or [])
    if expected_names and ff2:
        actual = {
            (x.get("font_name") or "").split("+", 1)[-1]
            for x in ff2
            if x.get("font_name")
        }
        if actual and actual.isdisjoint(expected_names):
            res.add(
                "ALFA_FONTFILE2_NAME_MISMATCH",
                f"шрифт {sorted(actual)} не из эталона канала {channel}: {sorted(expected_names)}",
            )
    return res


def run_alfa_spec_checks(pdf_bytes: bytes) -> AlfaSpecResult:
    out = AlfaSpecResult()
    text = _extract_text(pdf_bytes)
    producer, creator = _meta(pdf_bytes)
    channel = detect_alfa_channel(text)
    subtype = detect_alfa_subtype(text)
    out.stats["channel"] = channel
    out.stats["receipt_subtype"] = subtype
    out.stats["subtype_label"] = receipt_subtype_label(subtype=subtype)

    for part in (
        check_foreign_producer(pdf_bytes, producer, creator),
        check_oracle_bi_fonts(pdf_bytes),
        check_images_and_content(pdf_bytes),
        check_amounts(text),
        check_layout_family(text, channel),
        check_card_operation_id(text, channel),
        check_sbp_opid(text, channel),
        check_envelope(pdf_bytes, text, channel),
        check_fontfile2_profile(pdf_bytes, channel),
    ):
        out.flags.extend(part.flags)
        out.stats.update(part.stats)
    return out


def spec_to_log_dict(result: AlfaSpecResult) -> dict:
    return {
        "flags": [{"code": f.code, "detail": f.detail} for f in result.flags],
        "stats": result.stats,
    }
