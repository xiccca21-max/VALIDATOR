"""Gazprombank receipt emitter detection, families and field extraction (spec §2, §11)."""

from __future__ import annotations

import re
from datetime import datetime

FAMILY_SBP_PHONE = "GPB-SBP"
FAMILY_CARD = "GPB-CARD"
FAMILY_NEW = "NEW_GPB_PROFILE"

FAMILY_LABELS = {
    FAMILY_SBP_PHONE: "Перевод по номеру телефона / СБП",
    FAMILY_CARD: "Перевод по номеру карты",
    FAMILY_NEW: "Новый GPB-профиль",
}

SBER_EXCLUDED_SHA_PREFIXES = ("bdaec803", "31976c7f")

_SBP_ID_RE = re.compile(r"^[A-Z0-9]{32}$")
_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{2}):(\d{2})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"([\d\s\u00a0\u202f]+(?:,\d{2})?)\s*руб",
    re.IGNORECASE,
)
_ITEXT7_MARKERS = ("itext® 7", "itext 7.1.10")
_JASPER_MARKERS = ("jasperreports", "itext 2.1.7")


def _norm(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()


def is_excluded_sber_hash(file_hash: str) -> bool:
    h = (file_hash or "").lower()
    return any(h.startswith(p) for p in SBER_EXCLUDED_SHA_PREFIXES)


def detect_emitter(text: str, pdf_bytes: bytes, file_hash: str = "") -> str:
    """Emitter by branding/footer/provenance — NOT recipient bank (spec §2.1)."""
    if file_hash and is_excluded_sber_hash(file_hash):
        return "sber"

    low = _norm(text)
    gpb_footer = (
        "mailbox@gazprombank.ru" in low
        or "www.gazprombank.ru" in low
        or "+7 (495) 719-1763" in (text or "")
    )
    sber_layout = (
        "номер операции в сбп" in low
        and "перевод по сбп" in low
        and not gpb_footer
    )
    sber_brand = "пao сбербанк" in low or "сбер банк" in low or "сбербанк" in low

    if sber_layout or (sber_brand and not gpb_footer):
        return "sber"
    if gpb_footer or "газпромбанк" in low:
        return "gpb"
    if b"mailbox@gazprombank" in pdf_bytes or b"www.gazprombank" in pdf_bytes:
        return "gpb"
    return "unknown"


def detect_generator_path(producer: str, creator: str = "") -> str:
    blob = f"{producer} {creator}".lower()
    if any(m in blob for m in _ITEXT7_MARKERS):
        return "itext7"
    if any(m in blob for m in _JASPER_MARKERS):
        return "jasper_itext2_pdfa"
    return "unknown_coherent"


def classify_family(text: str) -> str:
    low = _norm(text)
    if "дебетовый перевод" in low and "перевод по номеру карты" in low:
        return FAMILY_CARD
    if "перевод по номеру телефона" in low or "номер операции сбп" in low:
        return FAMILY_SBP_PHONE
    if "чек по операции" in low:
        return FAMILY_NEW
    return FAMILY_NEW


def family_label(code: str) -> str:
    return FAMILY_LABELS.get(code, code)


def is_gazprombank_receipt(text: str, pdf_bytes: bytes, file_hash: str = "") -> bool:
    return detect_emitter(text, pdf_bytes, file_hash) == "gpb"


def parse_operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    for label in ("дата и время операции",):
        idx = raw.lower().find(label)
        if idx >= 0:
            m = _DATE_RE.search(raw[idx:idx + 100])
            if m:
                d, mo, y, h, mi = map(int, m.groups())
                try:
                    return datetime(y, mo, d, h, mi, 0)
                except ValueError:
                    pass
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
    low = compact.lower()
    for marker in ("номероперациисбп", "номероперациивсбп"):
        idx = low.find(marker)
        if idx >= 0:
            tail = compact[idx + len(marker):idx + len(marker) + 40]
            m = re.match(r"([A-Z0-9]{32})", tail)
            if m:
                return m.group(1)
    m = re.search(r"([AB][0-9A-Z]{31})", compact)
    if m and _SBP_ID_RE.match(m.group(1)):
        return m.group(1)
    m = re.search(r"([A-Z0-9]{32})", compact)
    return m.group(1) if m and _SBP_ID_RE.match(m.group(1)) else None


def _parse_amount_after_label(label: str, text: str) -> float | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    lines = raw.splitlines()
    target = label.lower().rstrip(":")
    for i, ln in enumerate(lines):
        if target in ln.lower():
            for nxt in lines[i:i + 4]:
                m = _AMOUNT_RE.search(nxt)
                if m:
                    num = m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
                    try:
                        return float(num)
                    except ValueError:
                        pass
    return None


def check_total_arithmetic(text: str) -> tuple[bool, str]:
    """Сумма с учётом комиссии = Сумма + Сумма комиссии."""
    total = _parse_amount_after_label("сумма с учётом комиссии", text)
    amount = _parse_amount_after_label("сумма", text)
    fee = _parse_amount_after_label("сумма комиссии", text)
    if total is None or amount is None or fee is None:
        return False, ""
    expected = round(amount + fee, 2)
    actual = round(total, 2)
    if abs(expected - actual) > 0.02:
        return True, (
            f"Итого {actual:.2f} ≠ Сумма {amount:.2f} + Комиссия {fee:.2f} "
            f"(ожидалось {expected:.2f})"
        )
    return False, ""
