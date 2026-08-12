"""Sber receipt checks — legacy score engine (disabled at 100% sber_v1 rollout)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from .tbank import _SIGNALS

_PDF_DATE_RE = re.compile(r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")
_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_SBER_DATE_RE = re.compile(
    r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?",
    re.IGNORECASE,
)
_SBER_AMOUNT_BAD_RE = re.compile(r"\b\d{4,}\s*₽|\b0{2,}[.,]0\s*₽")
_SBER_SBP_ID_LINE_RE = re.compile(r"([ABАВ][0-9A-ZА-Я]{20,40})")
_SBER_SBP_ID_RE = re.compile(r"^[AB][0-9A-Z]{31}$")


def _text_and_meta(pdf_bytes: bytes) -> tuple[str, dict]:
    if not fitz:
        return "", {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        meta = dict(doc.metadata or {})
        doc.close()
        return text, meta
    except Exception:
        return "", {}


def _parse_pdf_date(value: str) -> datetime | None:
    m = _PDF_DATE_RE.match(value or "")
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _parse_sber_operation_time(text: str) -> datetime | None:
    m = _SBER_DATE_RE.search((text or "").replace("\xa0", " "))
    if not m:
        return None
    day_s, month_s, year_s, hour_s, minute_s, second_s = m.groups()
    month = _RU_MONTHS.get(month_s.lower())
    if not month:
        return None
    try:
        return datetime(
            int(year_s), month, int(day_s),
            int(hour_s), int(minute_s), int(second_s or 0),
        )
    except ValueError:
        return None


def _has_bad_amount_format(text: str) -> bool:
    compact = (text or "").replace("\xa0", " ")
    return bool(_SBER_AMOUNT_BAD_RE.search(compact))


def _invalid_sbp_id(text: str) -> str | None:
    if "Номер операции в СБП" not in (text or ""):
        return None
    lines = [(ln or "").strip().replace("\xa0", " ") for ln in (text or "").splitlines()]
    candidates: list[str] = []
    for i, ln in enumerate(lines):
        if "Номер операции в СБП" in ln:
            candidates.extend(lines[i + 1:i + 4])
    candidates.append(re.sub(r"\s+", "", text or ""))

    m = None
    for candidate in candidates:
        m = _SBER_SBP_ID_LINE_RE.search(re.sub(r"\s+", "", candidate))
        if m:
            break
    if not m:
        return "не найден структурный идентификатор операции СБП"
    opid = m.group(1)
    if _SBER_SBP_ID_RE.match(opid):
        return None
    return f"идентификатор операции СБП имеет неверный алфавит/длину: {opid[:34]}"


def _trailing_data_after_eof(pdf_bytes: bytes) -> bool:
    pos = pdf_bytes.rfind(b"%%EOF")
    return pos >= 0 and bool(pdf_bytes[pos + 5:].strip())


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    text, meta = _text_and_meta(pdf_bytes)
    flags: list[str] = []
    score = 0
    details = {
        "bank_key": "sber",
        "producer": meta.get("producer", ""),
        "creator": meta.get("creator", ""),
        "file_hash": file_hash,
    }

    creation = _parse_pdf_date(meta.get("creationDate", ""))
    operation = _parse_sber_operation_time(text)
    details["operation_time"] = operation.isoformat(sep=" ") if operation else None
    details["creation_time"] = creation.isoformat(sep=" ") if creation else None

    if creation and operation and operation > creation:
        flags.append(
            "[SBER_OPERATION_AFTER_PDF_CREATION] дата операции позже CreationDate PDF"
        )
        score += _SIGNALS["forensic_high"]

    low = (text or "").lower()
    if "сейчас" in low:
        flags.append(
            "[SBER_DYNAMIC_NOW_IN_STATIC_RECEIPT] в сохранённом PDF дата операции оставлена как «сейчас»"
        )
        score += _SIGNALS["forensic_high"]

    if "\x00" in text or "\ufffd" in text or "൚" in text:
        flags.append(
            "[SBER_TEXT_LAYER_CORRUPT] в текстовом слое битые символы / неверный знак рубля"
        )
        score += _SIGNALS["forensic_high"]

    if re.search(r"\d+[.,]\d{2}\s*൚", text or ""):
        flags.append(
            "[SBER_AMOUNT_GLYPH_CORRUPT] сумма напечатана с чужим glyph вместо ₽"
        )
        score += _SIGNALS["forensic_high"]

    if _has_bad_amount_format(text):
        flags.append(
            "[SBER_AMOUNT_FORMAT_ANOMALY] сумма/комиссия напечатана не в формате Сбера"
        )
        score += _SIGNALS["forensic_high"]

    sbp_bad = _invalid_sbp_id(text)
    if sbp_bad:
        flags.append(f"[SBER_SBP_OPID_INVALID] {sbp_bad}")
        score += _SIGNALS["forensic_high"]

    if _trailing_data_after_eof(pdf_bytes):
        flags.append("[TRAILING_DATA_AFTER_EOF] после последнего %%EOF есть непустые данные")
        score += _SIGNALS["forensic_high"]

    from .verdict import finalize_verdict

    verdict, emoji, effective_score, forgery_flags = finalize_verdict(score, flags)
    details["user_message"] = (
        "Обнаружена подделка." if verdict == "ФЕЙК"
        else "Признаков подделки не найдено."
    )
    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": effective_score,
        "flags": forgery_flags,
        "details": details,
    }
