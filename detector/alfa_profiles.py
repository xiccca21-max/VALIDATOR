"""
Профили и константы эталонных чеков Альфа-Банка.
Генератор: Oracle BI Publisher 12.2.1.4.0 (не Jasper/OpenPDF).

Каналы — для envelope и условных проверок.
Подтипы — подписи в боте (СБП, телефон Альфа→Альфа, карта→Альфа, карта→другой банк).
"""

from __future__ import annotations

import re

PROFILE_VERSION = "alfa_corpus_2026_06"

CHANNEL_SBP = "sbp"
CHANNEL_PHONE = "phone"
CHANNEL_CARD = "card"

SUBTYPE_SBP = "sbp"
SUBTYPE_INTRABANK_PHONE = "intrabank_phone"
SUBTYPE_CARD_INTRABANK = "card_intrabank"
SUBTYPE_CARD_INTERBANK = "card_interbank"
SUBTYPE_UNKNOWN = "unknown"

ALFA_IMAGE_SIZES = frozenset({(900, 105), (90, 138), (603, 258)})

ALFA_SHELL = {
    "producer_substr": "Oracle BI Publisher",
    "pdf_version": "1.6",
    "object_count": 16,
    "eof_count": 1,
    "creator_empty": True,
}

ALFA_NATIVE_PRODUCERS = ("oracle bi publisher",)

ALFA_FOREIGN_PRODUCERS = (
    "pikepdf", "pypdf", "reportlab", "ilovepdf", "smallpdf", "pdfedit",
    "openpdf", "jasperreports", "itext", "wkhtmltopdf",
)

# BIN первых 6 цифр карт Альфа-Банка (для «с карты на карту»)
ALFA_CARD_BINS = frozenset({
    "220015", "220220", "415481", "437772", "458410", "479087",
    "521178", "548601", "548655", "552175", "555949", "676230",
})

_SBP_ID_RE = re.compile(r"[AB][0-9A-Z]{31}")
_BANK_OP_SBP_RE = re.compile(r"C\d{15}")
_BANK_OP_CARD_RE = re.compile(r"Z\d{15}")
_CARD_MASK_RE = re.compile(r"(\d{6})\*+\d{4}")
_RECIPIENT_BANK_RE = re.compile(
    r"банк\s+получателя\s*\n?\s*(.+?)(?:\n|счёт|счет|идентификатор|сообщение)",
    re.IGNORECASE | re.DOTALL,
)


def _norm(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).lower()


def _is_alfa_bank_name(name: str) -> bool:
    n = _norm(name)
    return any(m in n for m in ("альфа-банк", "альфа банк", "alfa-bank", "alfa bank"))


def _extract_recipient_bank(text: str) -> str:
    raw = (text or "").replace("\xa0", " ")
    m = _RECIPIENT_BANK_RE.search(raw)
    if m:
        return m.group(1).strip()
    low = _norm(text)
    idx = low.find("банк получателя")
    if idx >= 0:
        tail = raw[idx:].split("\n", 2)
        if len(tail) > 1:
            return tail[1].strip()
    return ""


def _extract_card_bin(text: str, recipient: bool = True) -> str | None:
    raw = (text or "").replace("\xa0", " ")
    label = "номер карты получателя" if recipient else "номер карты отправителя"
    low = raw.lower()
    idx = low.find(label)
    if idx < 0:
        return None
    chunk = raw[idx: idx + 120]
    m = _CARD_MASK_RE.search(chunk)
    return m.group(1) if m else None


def _has_sbp_markers(text: str) -> bool:
    low = _norm(text)
    flat = re.sub(r"\s+", "", text or "")
    if _SBP_ID_RE.search(flat):
        return True
    return any(m in low for m in (
        "квитанция о переводе по сбп",
        "идентификатор операции в сбп",
        "идентификатор операции сбп",
    ))


def _has_card_markers(text: str) -> bool:
    low = _norm(text)
    return any(m in low for m in (
        "квитанция о переводе с карты",
        "с карты на карту",
        "номер карты получателя",
        "номер карты отправителя",
    ))


def _has_phone_intrabank_markers(text: str) -> bool:
    if _has_sbp_markers(text) or _has_card_markers(text):
        return False
    low = _norm(text)
    if not any(m in low for m in (
        "по номеру телефона",
        "номер телефона получателя",
        "перевод клиенту",
        "квитанция о переводе",
    )):
        return False
    bank = _extract_recipient_bank(text)
    return _is_alfa_bank_name(bank)


def detect_alfa_channel(text: str) -> str:
    """Канал: sbp | phone | card."""
    if not text:
        return CHANNEL_PHONE
    if _has_sbp_markers(text):
        return CHANNEL_SBP
    if _has_card_markers(text):
        return CHANNEL_CARD
    if _has_phone_intrabank_markers(text):
        return CHANNEL_PHONE
    low = _norm(text)
    if "идентификатор операции" in low and "сбп" in low:
        return CHANNEL_SBP
    if _BANK_OP_CARD_RE.search(re.sub(r"\s+", "", text or "")):
        return CHANNEL_CARD
    return CHANNEL_PHONE


def detect_alfa_subtype(text: str) -> str:
    """Подтип для подписи в боте."""
    if not text:
        return SUBTYPE_UNKNOWN

    if _has_sbp_markers(text):
        return SUBTYPE_SBP

    if _has_card_markers(text):
        bank = _extract_recipient_bank(text)
        if _is_alfa_bank_name(bank):
            return SUBTYPE_CARD_INTRABANK
        rcv_bin = _extract_card_bin(text, recipient=True)
        if rcv_bin and rcv_bin in ALFA_CARD_BINS:
            return SUBTYPE_CARD_INTRABANK
        return SUBTYPE_CARD_INTERBANK

    if _has_phone_intrabank_markers(text):
        return SUBTYPE_INTRABANK_PHONE

    channel = detect_alfa_channel(text)
    if channel == CHANNEL_SBP:
        return SUBTYPE_SBP
    if channel == CHANNEL_CARD:
        return SUBTYPE_CARD_INTERBANK
    if channel == CHANNEL_PHONE:
        return SUBTYPE_INTRABANK_PHONE
    return SUBTYPE_UNKNOWN


def receipt_subtype_label(subtype: str | None = None, channel: str | None = None) -> str:
    """Подпись типа чека в боте."""
    labels = {
        SUBTYPE_SBP: "СБП Альфа-Банк",
        SUBTYPE_INTRABANK_PHONE: "Чек Альфа-Банк, по телефону (Альфа→Альфа)",
        SUBTYPE_CARD_INTRABANK: "Чек Альфа-Банк, с карты на карту (Альфа)",
        SUBTYPE_CARD_INTERBANK: "Чек Альфа-Банк, с карты на карту (другой банк)",
        SUBTYPE_UNKNOWN: "Чек Альфа-Банк",
    }
    if subtype:
        return labels.get(subtype, "Чек Альфа-Банк")
    if channel == CHANNEL_SBP:
        return labels[SUBTYPE_SBP]
    if channel == CHANNEL_CARD:
        return labels[SUBTYPE_CARD_INTERBANK]
    if channel == CHANNEL_PHONE:
        return labels[SUBTYPE_INTRABANK_PHONE]
    return "Чек Альфа-Банк"


def extract_sbp_opid(text: str) -> str | None:
    flat = re.sub(r"\s+", "", text or "")
    m = _SBP_ID_RE.search(flat)
    return m.group(0) if m else None


def extract_bank_operation_id(text: str, channel: str) -> str | None:
    flat = re.sub(r"\s+", "", text or "")
    if channel == CHANNEL_CARD:
        m = _BANK_OP_CARD_RE.search(flat) or _BANK_OP_SBP_RE.search(flat)
    else:
        m = _BANK_OP_SBP_RE.search(flat)
    return m.group(0) if m else None
