"""Sparse-9 issuer router and per-bank contracts (spec router_policy + bank_contracts)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

BANK_KEYS = (
    "wbbank", "otp", "psb", "bchpb", "raif", "rocket", "sovkom", "uralsib", "yandex",
    "mts", "yoomoney", "rsbank", "tochka",
)

SPEC_IDS = {
    "wbbank": "WB_BANK",
    "otp": "OTP_BANK",
    "psb": "PSB",
    "bchpb": "BSPB",
    "raif": "RAIFFEISEN",
    "rocket": "ROCKET",
    "sovkom": "SOVCOMBANK",
    "uralsib": "URALSIB",
    "yandex": "YANDEX_BANK",
    "mts": "MTS_DENGI",
    "yoomoney": "YOOMONEY",
    "rsbank": "RUSSIAN_STANDARD",
    "tochka": "TOCHKA",
}

_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{2}):(\d{2})",
    re.IGNORECASE,
)
_DATE_RE2 = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_DATE_RE_RU = re.compile(
    r"(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+"
    r"(\d{4})\s+года(?:\s+в)?\s+(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)
_DATE_RE_RU_BARE = re.compile(
    r"(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+"
    r"(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
    re.IGNORECASE,
)
_DATE_RE_DMY_HM = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?",
)
_SBP_ID_RE = re.compile(r"^[A-Z0-9]{32}$")
_AMOUNT_RE = re.compile(
    r"([\d\s\u00a0\u202f]+(?:,\d{2})?)\s*(?:руб|₽)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BankContract:
    key: str
    spec_id: str
    display_name: str
    sbp_id_required: bool
    sbp_drift_min: int
    sbp_drift_max: int
    sbp_hard_minutes: int = 5


BANK_CONTRACTS: dict[str, BankContract] = {
    "wbbank": BankContract("wbbank", "WB_BANK", "ВБ Банк", False, -120, 120),
    "otp": BankContract("otp", "OTP_BANK", "ОТП Банк", True, 20, 40),
    "psb": BankContract("psb", "PSB", "Промсвязьбанк", True, -10, 0),
    "bchpb": BankContract("bchpb", "BSPB", "Банк Санкт-Петербург", True, 0, 60),
    "raif": BankContract("raif", "RAIFFEISEN", "Райффайзенбанк", True, 0, 60),
    "rocket": BankContract("rocket", "ROCKET", "Рокетбанк", True, 0, 60),
    "sovkom": BankContract("sovkom", "SOVCOMBANK", "Совкомбанк", False, -120, 120),
    "uralsib": BankContract("uralsib", "URALSIB", "Уралсиб", True, 0, 60),
    "yandex": BankContract("yandex", "YANDEX_BANK", "Яндекс Банк", True, 0, 60),
    "mts": BankContract("mts", "MTS_DENGI", "МТС Деньги", True, -120, 120),
    "yoomoney": BankContract("yoomoney", "YOOMONEY", "ЮMoney", False, -120, 120),
    "rsbank": BankContract("rsbank", "RUSSIAN_STANDARD", "Русский Стандарт", True, -120, 120),
    "tochka": BankContract("tochka", "TOCHKA", "Точка Банк", True, -120, 120),
}


def _norm(text: str) -> str:
    return (text or "").replace("\xa0", " ").replace("\u202f", " ").lower()


def _field_value(text: str, label: str) -> str:
    raw = (text or "").replace("\xa0", " ")
    lines = [ln.strip() for ln in raw.splitlines()]
    target = label.lower().rstrip(":")
    for i, ln in enumerate(lines):
        if target in ln.lower():
            rest = ln.split(":", 1)
            if len(rest) > 1 and rest[1].strip():
                return rest[1].strip()
            for nxt in lines[i + 1:i + 4]:
                if nxt.strip():
                    return nxt.strip()
    return ""


def detect_issuer(text: str, producer: str, creator: str, pdf_bytes: bytes) -> str | None:
    """Issuer by branding/footer/provenance — never recipient bank alone."""
    low = _norm(text)
    pr = (producer or "").lower()
    cr = (creator or "").lower()
    blob = f"{pr} {cr}"

    if cr.strip() == "dbo-print-forms" or (
        "код транзакции" in low and "код операции сбп" in low
    ):
        return "mts"

    if "номер кошелька" in low or b"FactorIO-Regular" in (pdf_bytes or b""):
        return "yoomoney"

    if (
        "банк в кармане" in low
        or ("044525151" in (text or "").replace(" ", "") and "чек операции" in low)
    ):
        return "rsbank"

    if (
        "банк точка" in low
        or b"TTNormsTochka" in (pdf_bytes or b"")
        or ("044525104" in (text or "").replace(" ", "") and "исходящий перевод через сбп" in low)
    ):
        return "tochka"

    if "вб банк" in low and ("jasperreports library version 7" in cr or "openpdf" in pr):
        return "wbbank"

    if (
        "7708001614" in text
        or ("акционерное общество" in low and "отп банк" in low)
        or "ао «отп банк»" in low
        or "ао «отп банк»" in low.replace("«", "").replace("»", "")
    ) and (
        "quartz pdfcontext" in pr
        or "mpdf" in pr
        # New OTP phone path: iText Core + pdfHTML (AGPL), seen on genuines
        # e.g. JCTCSJD6 — previously NOT_BANK_RECEIPT under sparse9 live.
        or "itext" in pr
        or "pdfhtml" in pr
        or "itext" in blob
        or "pdfhtml" in blob
    ):
        return "otp"

    if "fastreport" in pr and "чек по операции" in low and "id операции сбп" in low:
        return "psb"

    if (
        "банк санкт-петербург" in low
        or 'банк "санкт-петербург"' in low
        or "бспб" in low
    ) and ("pdfcreator" in cr or "pdfproducer" in pr):
        return "bchpb"

    sender_raif = _field_value(text, "банк отправителя")
    if (
        "ао «райффайзенбанк»" in low
        or "online.raiffeisen.ru" in low
        or ("справка по операции" in low and "смоленская-сенная" in low)
        or "райффайзенбанк" in _norm(sender_raif)
    ):
        return "raif"

    sender_rocket = _field_value(text, "банк отправителя")
    if (
        ("банк отправителя" in low and "рокет" in _norm(sender_rocket))
        or ("itext® core 9" in pr and "перевод через сбп" in low)
        or ("itext core 9" in pr and "исходящий" in low)
    ):
        return "rocket"

    if "flying saucer" in blob and "платежная квитанция" in low:
        return "sovkom"

    if "rpdf.0.9" in pr or ("8-800-250-57-57" in text and "квитанция" in low):
        return "uralsib"

    sender_yandex = _field_value(text, "банк отправителя")
    if (
        "яндекс банк" in _norm(sender_yandex)
        or (
            "jasperreports library version 6.21" in cr
            and "исходящий перевод сбп" in low
            and "дата и время операции мск" in low
        )
    ):
        return "yandex"

    if b"wildberries" in pdf_bytes.lower() or b"\xd0\xb2\xd0\xb1 \xd0\xb1\xd0\xb0\xd0\xbd\xd0\xba" in pdf_bytes.lower():
        return "wbbank"

    return None


def classify_method(text: str, bank_key: str) -> str:
    low = _norm(text)
    if bank_key == "yoomoney":
        return "CARD_TRANSFER"
    if bank_key == "sovkom" or "по номеру карты" in low:
        return "CARD_TRANSFER"
    if "перевод по номеру телефона" in low or "рублевый перевод по номеру телефона" in low:
        return "PHONE_TRANSFER"
    if "сбп" in low or "система быстрых платежей" in low or "исходящий перевод сбп" in low:
        return "SBP_OUT"
    if "на карту другого банка" in low:
        return "CARD_OTHER_BANK"
    return "GENERIC"


def method_label(code: str) -> str:
    return {
        "SBP_OUT": "Исходящий перевод СБП",
        "PHONE_TRANSFER": "Перевод по номеру телефона",
        "CARD_TRANSFER": "Перевод по номеру карты",
        "CARD_OTHER_BANK": "На карту другого банка",
        "GENERIC": "Операция банка",
    }.get(code, code)


def parse_operation_datetime(text: str, bank_key: str = "") -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    if bank_key == "tochka":
        m = _DATE_RE_RU_BARE.search(raw)
        if m:
            d = int(m.group(1))
            mo = _RU_MONTHS[m.group(2).lower()]
            y, h, mi = int(m.group(3)), int(m.group(4)), int(m.group(5))
            sec = int(m.group(6) or 0)
            try:
                return datetime(y, mo, d, h, mi, sec)
            except ValueError:
                pass
    if bank_key in ("mts", "rsbank", "yoomoney"):
        m = _DATE_RE.search(raw) or _DATE_RE2.search(raw) or _DATE_RE_DMY_HM.search(raw)
        if m:
            g = m.groups()
            d, mo, y, h, mi = map(int, g[:5])
            sec = int(g[5]) if len(g) > 5 and g[5] else 0
            try:
                return datetime(y, mo, d, h, mi, sec)
            except ValueError:
                pass
    if bank_key == "yandex":
        m = re.search(
            r"дата и время операции мск\s*(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{2}):(\d{2})",
            raw, re.I,
        )
        if m:
            d, mo, y, h, mi = map(int, m.groups())
            try:
                return datetime(y, mo, d, h, mi, 0)
            except ValueError:
                pass

    # Raif pdfHTML: «21 июля 2026 года в 21:47 МСК»
    if bank_key in ("raif", "raiffeisen", ""):
        for label in ("дата и время", "дата выдачи"):
            idx = raw.lower().find(label)
            if idx < 0:
                continue
            chunk = raw[idx:idx + 160]
            m = _DATE_RE_RU.search(chunk)
            if m:
                d = int(m.group(1))
                mo = _RU_MONTHS[m.group(2).lower()]
                y, h, mi = int(m.group(3)), int(m.group(4)), int(m.group(5))
                try:
                    return datetime(y, mo, d, h, mi, 0)
                except ValueError:
                    pass
        m = _DATE_RE_RU.search(raw)
        if m:
            d = int(m.group(1))
            mo = _RU_MONTHS[m.group(2).lower()]
            y, h, mi = int(m.group(3)), int(m.group(4)), int(m.group(5))
            try:
                return datetime(y, mo, d, h, mi, 0)
            except ValueError:
                pass

    for label in (
        "дата операции", "дата и время", "дата и время операции",
        "дата и время операции мск", "дата:",
    ):
        idx = raw.lower().find(label.lower())
        if idx >= 0:
            chunk = raw[idx:idx + 120]
            m = _DATE_RE.search(chunk) or _DATE_RE2.search(chunk)
            if m:
                g = m.groups()
                if len(g) == 5:
                    d, mo, y, h, mi = map(int, g)
                    sec = 0
                else:
                    d, mo, y, h, mi, sec = map(int, g)
                try:
                    return datetime(y, mo, d, h, mi, sec)
                except ValueError:
                    pass
    m = _DATE_RE.search(raw) or _DATE_RE2.search(raw)
    if not m:
        return None
    g = m.groups()
    if len(g) == 5:
        d, mo, y, h, mi = map(int, g)
        sec = 0
    else:
        d, mo, y, h, mi, sec = map(int, g)
    try:
        return datetime(y, mo, d, h, mi, sec)
    except ValueError:
        return None


def extract_sbp_opid(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    low = compact.lower()
    for marker in (
        "номероперациивсбп", "идентификатороперациивсбп",
        "idоперациисбп", "кодоперациисбп", "идентификатороперации",
        "номероперации", "кодоперации",
    ):
        idx = low.find(marker)
        if idx >= 0:
            tail = compact[idx + len(marker):idx + len(marker) + 48]
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
    total = _parse_amount_after_label("итого", text)
    if total is None:
        total = _parse_amount_after_label("сумма с учётом комиссии", text)
    amount = _parse_amount_after_label("сумма", text)
    if amount is None:
        amount = _parse_amount_after_label("сумма операции", text)
    fee = _parse_amount_after_label("комиссия", text)
    if total is None or amount is None:
        return False, ""
    fee_val = fee if fee is not None else 0.0
    expected = round(amount + fee_val, 2)
    actual = round(total, 2)
    if abs(expected - actual) > 0.02:
        return True, (
            f"Итого {actual:.2f} ≠ Сумма {amount:.2f} + Комиссия {fee_val:.2f} "
            f"(ожидалось {expected:.2f})"
        )
    return False, ""
