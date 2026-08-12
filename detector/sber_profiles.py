"""Sber receipt submethod classification and field extraction (spec §10)."""

from __future__ import annotations

import re
from datetime import datetime

SUBMETHOD_P1 = "SBR-P1"  # card → other bank
SUBMETHOD_P2 = "SBR-P2"  # internal client (iText)
SUBMETHOD_P3 = "SBR-P3"  # internal client PDFium export
SUBMETHOD_P4 = "SBR-P4"  # legacy phone → other bank
SUBMETHOD_P5 = "SBR-P5"  # outgoing SBP
SUBMETHOD_P6 = "SBR-P6"  # SBP request

SUBMETHOD_LABELS = {
    SUBMETHOD_P1: "Перевод в другой банк по номеру карты",
    SUBMETHOD_P2: "Перевод клиенту СберБанка",
    SUBMETHOD_P3: "Перевод клиенту СберБанка (PDFium export)",
    SUBMETHOD_P4: "Перевод по номеру телефона (legacy)",
    SUBMETHOD_P5: "Перевод по СБП",
    SUBMETHOD_P6: "Перевод по запросу СБП",
}

_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_DATE_RE = re.compile(
    r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?",
    re.IGNORECASE,
)
_SBP_ID_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_LEGACY_DOC_RE = re.compile(r"^\d{14}[a-z0-9]{22}$")
_INTERNAL_DOC_RE = re.compile(r"^100\d{16}$")
_AMOUNT_RE = re.compile(r"([\d\s\u00a0\u202f]+(?:[.,]\d{2})?)\s*₽")

_IOS_MARKERS = ("quartz pdfcontext",)
_PDFIUM_MARKERS = ("pdfium",)
_JASPER_MARKERS = ("jasperreports",)
_ITEXT_MARKERS = ("itext",)


def _norm(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()


def detect_generator_path(producer: str, creator: str = "") -> str:
    blob = f"{producer} {creator}".lower()
    if any(m in blob for m in _IOS_MARKERS):
        return "ios_quartz"
    if any(m in blob for m in _PDFIUM_MARKERS):
        return "pdfium"
    if any(m in blob for m in _JASPER_MARKERS) or any(m in blob for m in _ITEXT_MARKERS):
        return "jasper_itext"
    return "unknown_coherent"


def classify_submethod(text: str, *, producer: str = "", creator: str = "") -> str:
    low = _norm(text)
    gen = detect_generator_path(producer, creator)

    if "перевод по запросу сбп" in low:
        return SUBMETHOD_P6
    if "перевод по сбп" in low or "номер операции в сбп" in low:
        return SUBMETHOD_P5
    if "перевод в другой банк по номеру карты" in low:
        return SUBMETHOD_P1
    if "перевод клиенту сбербанка" in low or "перевод клиенту сбер" in low:
        if gen == "pdfium":
            return SUBMETHOD_P3
        return SUBMETHOD_P2
    if "перевод по номеру телефона" in low:
        return SUBMETHOD_P4
    if "номер карты получателя" in low or "номер счёта получателя" in low:
        if gen == "pdfium":
            return SUBMETHOD_P3
        return SUBMETHOD_P2
    return "unknown"


def submethod_label(code: str) -> str:
    return SUBMETHOD_LABELS.get(code, code)


def is_sber_receipt(text: str, pdf_bytes: bytes) -> bool:
    low = _norm(text)
    jasper = b"JasperReports" in pdf_bytes
    quartz = b"Quartz PDFContext" in pdf_bytes

    # Non-Sber Jasper/iText issuers share the same tooling (ДОМ.РФ, ГПБ web, …).
    foreign_issuer = (
        "банк дом.рф" in low
        or "дом.рф" in low
        or "gazprombank.ru" in low
        or "mailbox@gazprombank.ru" in low
    )
    sber_brand = (
        "сбербанк" in low
        or "sberbank" in low
        or "перевод клиенту сбербанка" in low
    )
    if foreign_issuer and not sber_brand:
        return False

    if sber_brand:
        return True

    soft = (
        "перевод по сбп", "перевод клиенту",
        "перевод в другой банк", "перевод по номеру телефона",
        "перевод по запросу сбп", "чек по операции",
    )
    if any(m in low for m in soft) and (jasper or quartz):
        return True

    # SBP-outgoing Sber template often omits the word «Сбербанк» in the body.
    if (jasper or quartz) and (
        "номер операции в сбп" in low
        or ("сумма перевода" in low and "счёт отправителя" in low)
    ):
        return True

    return False


def parse_operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    for label in (
        "дата и время", "дата операции", "дата перевода",
    ):
        idx = raw.lower().find(label)
        if idx >= 0:
            m = _DATE_RE.search(raw[idx:idx + 120])
            if m:
                day_s, month_s, year_s, hour_s, minute_s, second_s = m.groups()
                month = _RU_MONTHS.get(month_s.lower())
                if month:
                    try:
                        return datetime(
                            int(year_s), month, int(day_s),
                            int(hour_s), int(minute_s), int(second_s or 0),
                        )
                    except ValueError:
                        pass
    m = _DATE_RE.search(raw)
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


def extract_sbp_opid(text: str) -> str | None:
    if "номер операции в сбп" not in _norm(text):
        return None
    lines = [(ln or "").strip().replace("\xa0", " ") for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        if "номер операции в сбп" in ln.lower():
            for nxt in lines[i + 1:i + 4]:
                token = re.sub(r"\s+", "", nxt)
                if _SBP_ID_RE.match(token):
                    return token
    compact = re.sub(r"\s+", "", text or "")
    m = re.search(r"([AB][0-9A-Z]{31})", compact)
    return m.group(1) if m else None


def extract_legacy_document(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    for m in re.finditer(r"(\d{14}[a-z0-9]{22})", compact):
        if _LEGACY_DOC_RE.match(m.group(1)):
            return m.group(1)
    return None


def extract_internal_document(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    for m in re.finditer(r"(100\d{16})", compact):
        if _INTERNAL_DOC_RE.match(m.group(1)):
            return m.group(1)
    return None


def _parse_amount(label: str, text: str) -> float | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    idx = raw.lower().find(label.lower())
    if idx < 0:
        return None
    chunk = raw[idx:idx + 80]
    m = _AMOUNT_RE.search(chunk)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def check_card_arithmetic(text: str) -> tuple[bool, str]:
    """P1: Списано = Сколько + Комиссия."""
    spent = _parse_amount("списано", text)
    amount = _parse_amount("сколько", text)
    fee = _parse_amount("комиссия", text)
    if spent is None or amount is None or fee is None:
        return False, ""
    expected = round(amount + fee, 2)
    actual = round(spent, 2)
    if abs(expected - actual) > 0.02:
        return True, (
            f"Списано {actual:.2f} ₽ ≠ Сколько {amount:.2f} + Комиссия {fee:.2f} "
            f"(ожидалось {expected:.2f})"
        )
    return False, ""
