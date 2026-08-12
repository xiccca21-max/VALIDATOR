"""Ozon receipt family classification and field extraction (spec §2, §10)."""

from __future__ import annotations

import re
from datetime import datetime

FAMILY_CARD_OUT = "CARD_OUT"
FAMILY_SBP_OUT = "SBP_OUT"
FAMILY_SBP_IN = "SBP_IN"
FAMILY_INTERNAL_PHONE_OUT = "INTERNAL_PHONE_OUT"
FAMILY_INTERNAL_PHONE_IN = "INTERNAL_PHONE_IN"
FAMILY_NEW = "NEW_OZON_PROFILE"

FAMILY_LABELS = {
    FAMILY_CARD_OUT: "Перевод на карту другого банка",
    FAMILY_SBP_OUT: "СБП — исходящий",
    FAMILY_SBP_IN: "СБП — входящий",
    FAMILY_INTERNAL_PHONE_OUT: "Телефон внутри Ozon — исходящий",
    FAMILY_INTERNAL_PHONE_IN: "Телефон внутри Ozon — входящий",
    FAMILY_NEW: "Новый Ozon-профиль",
}

_SBP_ID_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_PO_UUID_RE = re.compile(
    r"po-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"([\d\s\u00a0\u202f]+(?:,\d{2})?)\s*₽",
)
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})")
_AMOUNT_DISPLAY_RE = re.compile(
    r"^(?:0|[1-9]\d{0,2}(?: \d{3})*)(?:,\d{2})?\s*₽$"
)

_SKIA_MARKERS = ("skia/pdf", "chromium")


def _norm(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()


def is_skia_chromium_profile(producer: str = "", creator: str = "") -> bool:
    return detect_generator_path(producer, creator) == "chromium_skia"


def extract_labeled_amounts(text: str) -> list[tuple[str, str]]:
    """Return (label, raw amount line) for Итого/Сумма."""
    out: list[tuple[str, str]] = []
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        label = ln.strip()
        if label in ("Итого", "Сумма") and i + 1 < len(lines):
            out.append((label, lines[i + 1].strip()))
    return out


def check_amount_display_format(text: str) -> list[tuple[str, str]]:
    """Invalid Итого/Сумма lines for current Chromium/Skia profile (spec §10.1)."""
    bad: list[tuple[str, str]] = []
    for label, raw in extract_labeled_amounts(text):
        if not _AMOUNT_DISPLAY_RE.fullmatch(raw.replace("\u00a0", " ").replace("\u202f", " ")):
            bad.append((label, raw))
    return bad


def detect_generator_path(producer: str, creator: str = "") -> str:
    blob = f"{producer} {creator}".lower()
    if any(m in blob for m in _SKIA_MARKERS):
        return "chromium_skia"
    return "unknown_coherent"


def _has_bank_recipient(text: str) -> bool:
    low = _norm(text)
    return "банк получателя" in low or (
        "банк" in low and "получателя" in low and "отправителя" not in low.split("банк")[-1][:30]
    )


def _has_bank_sender(text: str) -> bool:
    low = _norm(text)
    return "банк отправителя" in low or (
        "банк" in low and "отправителя" in low
    )


def _has_32char_sbp_id(text: str) -> bool:
    return extract_sbp_opid(text) is not None


def classify_family(text: str) -> str:
    low = _norm(text)
    po_id = extract_po_uuid(text)

    if "номер карты получателя" in low and po_id:
        return FAMILY_CARD_OUT
    if "счёт списания" in low and _has_bank_recipient(text) and _has_32char_sbp_id(text):
        return FAMILY_SBP_OUT
    if "счёт зачисления" in low and _has_bank_sender(text) and _has_32char_sbp_id(text):
        return FAMILY_SBP_IN
    if "счёт списания" in low and "телефон получателя" in low:
        if not _has_bank_recipient(text) and not _has_32char_sbp_id(text):
            return FAMILY_INTERNAL_PHONE_OUT
    if "счёт зачисления" in low and "телефон отправителя" in low:
        if not _has_bank_sender(text) and not _has_32char_sbp_id(text):
            return FAMILY_INTERNAL_PHONE_IN
    if "озон банк" in low or "ozon" in low:
        return FAMILY_NEW
    return FAMILY_NEW


def family_label(code: str) -> str:
    return FAMILY_LABELS.get(code, code)


def is_ozon_receipt(text: str, pdf_bytes: bytes) -> bool:
    low = _norm(text)
    # OTP issuer footer/INN: Ozon may appear only as recipient bank — not Ozon receipt.
    low_plain = low.replace("«", "").replace("»", "").replace('"', "")
    if (
        "7708001614" in (text or "")
        or "акционерное общество «отп банк»" in low
        or "ао «отп банк»" in low
        or "ао отп банк" in low_plain
    ):
        return False
    if "озон банк" in low or "ozon банк" in low or "служба поддержки ozon" in low:
        return True
    return b"Skia/PDF" in pdf_bytes or b"Chromium" in pdf_bytes


def parse_operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    m = _DATE_RE.search(raw)
    if not m:
        return None
    d, mo, y, h, mi = map(int, m.groups())
    try:
        return datetime(y, mo, d, h, mi, 0)
    except ValueError:
        return None


def extract_sbp_opid(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    m = re.search(r"([AB][0-9A-Z]{31})", compact)
    if m and _SBP_ID_RE.match(m.group(1)):
        return m.group(1)
    lines = [(ln or "").strip() for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        if "id операции" in ln.lower() or "идентификатор операции" in ln.lower():
            chunk = re.sub(r"\s+", "", "".join(lines[i:i + 4]))
            m = re.search(r"([AB][0-9A-Z]{31})", chunk)
            if m:
                return m.group(1)
    return None


def extract_po_uuid(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    m = _PO_UUID_RE.search(compact)
    return m.group(0).lower() if m else None


def _parse_amount_value(raw: str) -> float | None:
    if not raw:
        return None
    low = raw.strip().lower()
    if "без комиссии" in low:
        return 0.0
    num = raw.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _field_amount(label: str, text: str) -> float | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    idx = raw.lower().find(label.lower())
    if idx < 0:
        return None
    chunk = raw[idx:idx + 80]
    m = _AMOUNT_RE.search(chunk)
    if not m:
        if label.lower() == "комиссия" and "без комиссии" in chunk.lower():
            return 0.0
        return None
    return _parse_amount_value(m.group(1))


def check_total_arithmetic(text: str) -> tuple[bool, str]:
    """Итого = Сумма + Комиссия (spec §10)."""
    total = _field_amount("итого", text)
    amount = _field_amount("сумма", text)
    fee = _field_amount("комиссия", text)
    if total is None or amount is None or fee is None:
        return False, ""
    expected = round(amount + fee, 2)
    actual = round(total, 2)
    if abs(expected - actual) > 0.02:
        return True, (
            f"Итого {actual:.2f} ₽ ≠ Сумма {amount:.2f} + Комиссия {fee:.2f} "
            f"(ожидалось {expected:.2f})"
        )
    return False, ""
