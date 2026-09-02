"""Bank-specific contracts from BANK_VALIDATORS_HARDENING_MASTER_v2_0."""

from __future__ import annotations

import json
from pathlib import Path

_KEY_MAP = {
    "vtb": "ВТБ",
    "sber": "СберБанк",
    "ozon": "Ozon Банк",
    "gazprombank": "Газпромбанк",
    "wbbank": "ВБ Банк",
    "otp": "ОТП Банк",
    "psb": "ПСБ",
    "bchpb": "БСПБ",
    "raif": "Райффайзенбанк",
    "rocket": "Рокетбанк",
    "sovkom": "Совкомбанк",
    "uralsib": "Уралсиб",
    "yandex": "Яндекс Банк",
    "mts": "МТС Деньги",
    "yoomoney": "ЮMoney",
    "rsbank": "Русский Стандарт",
    "tochka": "Точка Банк",
    "alfa": "Альфа-Банк",
}

_NO_EXPLICIT_STATUS = frozenset({"sber", "psb", "sovkom", "uralsib"})

_CARD_SUCCESS = frozenset({"обработано"})


def _load() -> list[dict]:
    p = Path(__file__).with_name("master.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("bank_contracts", [])
    except Exception:
        return []


def contract_for(bank_key: str) -> dict | None:
    name = _KEY_MAP.get(bank_key)
    if not name:
        return None
    for c in _load():
        if c.get("bank") == name:
            return c
    return None


def status_optional(bank_key: str) -> bool:
    return bank_key in _NO_EXPLICIT_STATUS


def card_success_ok(bank_key: str, submethod: str, phrase: str) -> bool:
    if bank_key == "otp" and submethod == "card":
        return phrase.lower().strip() in _CARD_SUCCESS
    return False
