"""
Каналы и подтипы чеков для всех банков (UI + условные проверки).
"""

from __future__ import annotations

import re

CHANNEL_SBP = "sbp"
CHANNEL_PHONE = "phone"
CHANNEL_CARD = "card"

SUBTYPE_SBP = "sbp"
SUBTYPE_PHONE_INTRABANK = "phone_intrabank"
SUBTYPE_PHONE_INTERBANK = "phone_interbank"
SUBTYPE_CARD_INTRABANK = "card_intrabank"
SUBTYPE_CARD_INTERBANK = "card_interbank"
SUBTYPE_UNKNOWN = "unknown"

_SBP_ID_RE = re.compile(r"[AB][0-9A-Z]{31}")

_BANK_MARKERS: dict[str, tuple[str, ...]] = {
    "tbank": ("т-банк", "тинькофф", "tinkoff", "tbank"),
    "alfa": ("альфа-банк", "alfa-bank", "alfa bank"),
    "sber": ("сбербанк", "сбер", "sberbank"),
    "vtb": ("втб", "vtb"),
    "gazprombank": ("газпромбанк", "gazprombank"),
    "ozon": ("озон банк", "ozon"),
    "yandex": ("яндекс банк", "yandex"),
    "psb": ("промсвязьбанк", "псб", "psbank"),
    "raif": ("райффайзен", "raiffeisen"),
    "otp": ("отп банк", "otp"),
    "uralsib": ("уралсиб", "uralsib"),
    "sovkom": ("совкомбанк", "sovcom"),
    "rocket": ("рокетбанк", "rocket bank"),
    "bchpb": ("бчпб", "бспб"),
    "mts": ("мтс деньги", "мтс банк"),
    "yoomoney": ("юmoney", "юмани"),
    "rsbank": ("русский стандарт", "банк в кармане"),
    "tochka": ("точка банк", "банк точка"),
}


def _norm(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).lower()


def _recipient_bank(text: str) -> str:
    raw = (text or "").replace("\xa0", " ")
    idx = raw.lower().find("банк получателя")
    if idx >= 0:
        lines = [ln.strip() for ln in raw[idx:].splitlines() if ln.strip()]
        if len(lines) > 1:
            return lines[1]
    return ""


def _is_own_bank(bank_name: str, bank_key: str) -> bool:
    bn = _norm(bank_name)
    for m in _BANK_MARKERS.get(bank_key, (bank_key,)):
        if m in bn:
            return True
    return False


def _has_sbp(text: str) -> bool:
    low = _norm(text)
    flat = re.sub(r"\s+", "", text or "")
    if _SBP_ID_RE.search(flat):
        return True
    return any(m in low for m in (
        "идентификатор операции в сбп",
        "квитанция о переводе по сбп",
        "исходящий перевод сбп",
        "id операции сбп",
        "номер операции в сбп",
    ))


def _has_card(text: str) -> bool:
    low = _norm(text)
    return any(m in low for m in (
        "с карты на карту",
        "квитанция о переводе с карты",
        "номер карты получателя",
        "номер карты отправителя",
        "по номеру карты",
        "перевод на карту",
        "карта получателя",
    ))


def _has_phone(text: str) -> bool:
    low = _norm(text)
    return any(m in low for m in (
        "по номеру телефона",
        "номер телефона получателя",
        "телефон получателя",
        "перевод клиенту",
        "перевод по номеру телефона",
    ))


def detect_channel(text: str, bank_key: str = "") -> str:
    if not text:
        return CHANNEL_PHONE
    if _has_sbp(text):
        return CHANNEL_SBP
    if _has_card(text):
        return CHANNEL_CARD
    if _has_phone(text):
        return CHANNEL_PHONE
    return CHANNEL_PHONE


def detect_subtype(text: str, bank_key: str, bank_display_name: str = "") -> str:
    if not text:
        return SUBTYPE_UNKNOWN
    channel = detect_channel(text, bank_key)
    rb = _recipient_bank(text)
    own = _is_own_bank(rb, bank_key) if rb else None

    if channel == CHANNEL_SBP:
        return SUBTYPE_SBP

    if channel == CHANNEL_CARD:
        if own is True:
            return SUBTYPE_CARD_INTRABANK
        if own is False:
            return SUBTYPE_CARD_INTERBANK
        return SUBTYPE_CARD_INTERBANK

    if channel == CHANNEL_PHONE:
        if own is True:
            return SUBTYPE_PHONE_INTRABANK
        if own is False:
            return SUBTYPE_PHONE_INTERBANK
        low = _norm(text)
        markers = _BANK_MARKERS.get(bank_key, ())
        if any(m in low for m in markers):
            return SUBTYPE_PHONE_INTRABANK
        return SUBTYPE_PHONE_INTERBANK

    return SUBTYPE_UNKNOWN


def receipt_subtype_label(
    subtype: str,
    bank_display_name: str,
    bank_key: str = "",
) -> str:
    name = bank_display_name or "Банк"
    labels = {
        SUBTYPE_SBP: f"СБП {name}",
        SUBTYPE_PHONE_INTRABANK: f"Чек {name}, по телефону",
        SUBTYPE_PHONE_INTERBANK: f"Чек {name}, по телефону",
        SUBTYPE_CARD_INTRABANK: f"Чек {name}, с карты на карту",
        SUBTYPE_CARD_INTERBANK: f"Чек {name}, с карты на карту",
        SUBTYPE_UNKNOWN: f"Чек {name}",
    }
    return labels.get(subtype, f"Чек {name}")
