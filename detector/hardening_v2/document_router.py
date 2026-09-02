"""Document router — G-DOC-001/002/003, issuer before authenticity."""

from __future__ import annotations

import re

_STATEMENT_MARKERS = (
    "выписка по счету", "выписка по карте", "bank statement", "statement of account",
    "остаток на начало", "остаток на конец", "opening balance", "closing balance",
    "дебет", "кредит", "обороты за период", "лист \\d+ из",
)
_RECEIPT_MARKERS = (
    "чек по операции", "квитанция", "квитанция о переводе", "платежная квитанция",
    "перевод", "итого", "сумма операции", "сумма перевода", "id операции",
    "идентификатор операции", "номер операции в сбп", "перевод по сбп",
    "счёт списания", "счет списания", "банк получателя", "исходящий перевод",
    "перевод на счет другому лицу", "сумма зачисления", "через сбп",
    "код операции сбп", "номер кошелька", "чек операции", "банк в кармане",
)
_UNSUPPORTED_CERT_MARKERS = (
    "справка о наличии", "справка о доходах", "справка для визы",
    "справка об открытии", "справка о закрытии", "2-ндфл",
)

_ISSUER_FOOTER: dict[str, tuple[str, ...]] = {
    "gazprombank": ("gazprombank.ru", "mailbox@gazprombank.ru", "газпромбанк"),
    "sber": ("сбербанк", "sberbank.ru", "900"),
    "vtb": ("банк втб", "vtb.ru", "втб (пао)"),
    "ozon": ("ozon банк", "ozon bank", "ozon.ru/fintech", "ozon.ru", "служба поддержки ozon"),
    "yandex": ("яндекс банк", "yandex.ru/finance", "яндекс"),
    "otp": ("отп банк", "7708001614", "отп"),
    "psb": ("пскб", "псб", "psbank.ru", "чек по операции"),
    "bchpb": ("банк \"санкт-петербург\"", "bspb.ru"),
    "raif": ("райффайзен", "raiffeisen.ru"),
    "rocket": ("рокетбанк", "rocketbank.ru"),
    "sovkom": ("совкомбанк", "sovcombank.ru"),
    "uralsib": ("уралсиб", "uralsib.ru"),
    "mts": ("код транзакции", "код операции сбп", "счет списания"),
    "yoomoney": ("номер кошелька", "перевод завершен"),
    "rsbank": ("банк в кармане", "044525151", "русский стандарт"),
    "tochka": ("банк точка", "044525104"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).lower()


def is_statement(text: str) -> bool:
    t = _norm(text)
    hits = sum(1 for m in _STATEMENT_MARKERS if re.search(m, t))
    if "выписка" in t and hits >= 1:
        return True
    if hits >= 2:
        return True
    return False


def is_unsupported_certificate(text: str, bank_key: str) -> bool:
    t = _norm(text)
    if bank_key == "raif" and "справка по операции" in t:
        return False
    if bank_key == "raif" and "квитанция" in t:
        return False
    for m in _UNSUPPORTED_CERT_MARKERS:
        if m in t:
            return True
    if t.count("справка") >= 2 and not any(x in t for x in _RECEIPT_MARKERS):
        return True
    return False


def looks_like_receipt(text: str) -> bool:
    t = _norm(text)
    return any(m in t for m in _RECEIPT_MARKERS)


def issuer_matches_bank(text: str, bank_key: str, producer: str = "") -> bool:
    markers = _ISSUER_FOOTER.get(bank_key, ())
    t = _norm(text)
    pr = (producer or "").lower()
    if bank_key == "sber":
        if any(x in t for x in (
            "перевод в другой банк", "перевод клиенту", "чек по операции",
            "от кого", "сколько", "списано", "сбербанк",
        )):
            return True
        if "quartz pdfcontext" in pr:
            return True
    if bank_key == "ozon" and "skia/pdf" in pr:
        return True
    if not markers:
        return True
    return any(m in t for m in markers)


def detect_submethod(text: str, bank_key: str) -> str:
    t = _norm(text)
    if any(x in t for x in ("идентификатор операции", "id операции", "сбп id", "номер операции в сбп", "через сбп")):
        return "sbp"
    if any(x in t for x in ("карт", "****", "••••")):
        if "телефон" in t or "+7" in t:
            return "phone"
        return "card"
    if "телефон" in t and "+7" in t:
        return "phone"
    if bank_key == "vtb" and "исходящий перевод сбп" in t:
        return "sbp"
    return "unknown"


def _receipt_confidence(text: str) -> int:
    t = _norm(text)
    return sum(1 for m in _RECEIPT_MARKERS if m in t)


def route_document(text: str, bank_key: str, producer: str = "") -> dict:
    """
    Returns document_class, supported, reason.
    Classes: SUPPORTED_RECEIPT, UNSUPPORTED_STATEMENT, UNSUPPORTED_CERTIFICATE, UNKNOWN_DOCUMENT
    """
    if is_statement(text):
        return {
            "document_class": "UNSUPPORTED_STATEMENT",
            "supported": False,
            "reason": "Определена банковская выписка",
        }
    if is_unsupported_certificate(text, bank_key):
        return {
            "document_class": "UNSUPPORTED_CERTIFICATE",
            "supported": False,
            "reason": "Неподдерживаемый тип справки",
        }
    if not looks_like_receipt(text):
        if bank_key and issuer_matches_bank(text, bank_key, producer) and len(_norm(text)) > 80:
            return {
                "document_class": "RECEIPT_NEW_PROFILE",
                "supported": False,
                "reason": "Новый профиль чека — поля не совпали с известным шаблоном",
            }
        return {
            "document_class": "UNKNOWN_DOCUMENT",
            "supported": False,
            "reason": "Не удалось определить поддерживаемый чек/квитанцию",
        }
    if bank_key and not issuer_matches_bank(text, bank_key, producer):
        if _receipt_confidence(text) < 2:
            return {
                "document_class": "UNKNOWN_DOCUMENT",
                "supported": False,
                "reason": "Эмитент документа не согласован с определённым банком",
            }
    return {
        "document_class": "SUPPORTED_RECEIPT",
        "supported": True,
        "submethod": detect_submethod(text, bank_key),
        "reason": "",
    }
