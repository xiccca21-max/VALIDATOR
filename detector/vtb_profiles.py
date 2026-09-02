"""VTB receipt family classification and field extraction (spec §2, §10)."""

from __future__ import annotations

import re
from datetime import datetime

FAMILY_SBP_OUT = "SBP_OUT"
FAMILY_CARD_OUT = "CARD_OUT"
FAMILY_PHONE_VTB = "PHONE_VTB"
FAMILY_NEW = "NEW_VTB_PROFILE"

FAMILY_LABELS = {
    FAMILY_SBP_OUT: "Исходящий перевод СБП",
    FAMILY_CARD_OUT: "Перевод на карту",
    FAMILY_PHONE_VTB: "По номеру телефона клиенту ВТБ",
    FAMILY_NEW: "Новый VTB-профиль",
}

_SBP_ID_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}),?\s*(\d{2}):(\d{2})")
_OPENHTML_MARKERS = ("openhtmltopdf",)


def _norm(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()


def detect_generator_path(producer: str, creator: str = "") -> str:
    blob = f"{producer} {creator}".lower()
    if any(m in blob for m in _OPENHTML_MARKERS):
        return "openhtmltopdf"
    if "openpdf" in blob:
        return "openpdf"
    return "unknown_coherent"


def classify_family(text: str) -> str:
    low = _norm(text)
    if "перевод на счет другому лицу" in low or "перевод на счёт другому лицу" in low:
        if "сбп" in low:
            return FAMILY_SBP_OUT
    if "исходящий перевод сбп" in low:
        return FAMILY_SBP_OUT
    if "денежный перевод" in low and "перевод на карту" in low:
        return FAMILY_CARD_OUT
    if "по номеру телефона клиенту втб" in low:
        return FAMILY_PHONE_VTB
    if "банк втб" in low or "втб (пао)" in low:
        return FAMILY_NEW
    return FAMILY_NEW


def family_label(code: str) -> str:
    return FAMILY_LABELS.get(code, code)


def is_vtb_receipt(text: str, pdf_bytes: bytes) -> bool:
    low = _norm(text)
    if any(m in low for m in (
        "банк втб", "втб (пао)", "исходящий перевод сбп",
        "перевод на карту", "по номеру телефона клиенту втб",
        "перевод на счет другому лицу", "перевод на счёт другому лицу",
    )):
        return True
    return b"openhtmltopdf" in pdf_bytes.lower()


def parse_operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    for label in ("дата операции",):
        idx = raw.lower().find(label)
        if idx >= 0:
            m = _DATE_RE.search(raw[idx:idx + 80])
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
    for marker in ("idоперациивсбп", "idоперации"):
        idx = low.find(marker)
        if idx >= 0:
            tail = compact[idx + len(marker):idx + len(marker) + 40]
            m = re.match(r"([AB][0-9A-Z]{31})", tail)
            if m:
                return m.group(1)
    m = re.search(r"([AB][0-9A-Z]{31})", compact)
    return m.group(1) if m and _SBP_ID_RE.match(m.group(1)) else None
