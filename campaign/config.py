"""Original-receipt collection campaign (19.07.2026 – 15.08.2026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Moscow = UTC+3 (no zoneinfo dependency on Windows)
MSK = timezone(timedelta(hours=3))

CAMPAIGN_ID = "originals_2026_07"
CAMPAIGN_TITLE = "Сбор оригинальных чеков"

# Inclusive window in Moscow time
CAMPAIGN_START = datetime(2026, 7, 19, 0, 0, 0, tzinfo=MSK)
CAMPAIGN_END = datetime(2026, 8, 15, 23, 59, 59, tzinfo=MSK)

# Operation date must be on/after this calendar day (MSK)
MIN_OPERATION_DATE = datetime(2026, 7, 19, 0, 0, 0, tzinfo=MSK).date()

CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS = 1000  # 10 ₽

# User-facing milestones (accepted count → rubles)
REWARD_MILESTONES = (
    (100, 1_000),
    (500, 5_000),
    (1_000, 10_000),
)

# Internal profile keys → campaign bank keys
SUPPORTED_BANKS = frozenset({
    "alfa",
    "sber",
    "vtb",
    "gazprombank",
    "psb",
    "raiffeisen",
    "ozon",
    "otp",
    "uralsib",
    "yandex",
    "sovcombank",
    "rocketbank",
    "bchpb",
})

# Map detector profile keys to campaign bank keys
BANK_KEY_ALIASES = {
    "tbank": "tbank",
    "alfa": "alfa",
    "alfa_ios": "alfa",
    "sber": "sber",
    "vtb": "vtb",
    "gazprombank": "gazprombank",
    "psb": "psb",
    "raif": "raiffeisen",
    "raiffeisen": "raiffeisen",
    "ozon": "ozon",
    "otp": "otp",
    "uralsib": "uralsib",
    "yandex": "yandex",
    "sovkom": "sovcombank",
    "sovcombank": "sovcombank",
    "rocket": "rocketbank",
    "rocketbank": "rocketbank",
    "bchpb": "bchpb",
}

BANK_DISPLAY = {
    "alfa": "Альфа-Банк",
    "sber": "Сбербанк",
    "vtb": "Банк ВТБ",
    "gazprombank": "Газпромбанк",
    "psb": "Промсвязьбанк",
    "raiffeisen": "Райффайзенбанк",
    "ozon": "Озон Банк",
    "otp": "ОТП Банк",
    "uralsib": "Уралсиб",
    "yandex": "Яндекс Банк",
    "sovcombank": "Совкомбанк",
    "rocketbank": "Рокетбанк",
    "bchpb": "Банк Санкт-Петербург",
}

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_DUPLICATE = "duplicate"
STATUS_FAKE = "fake"
STATUS_UNSUPPORTED = "unsupported"
STATUS_REVERSED = "reversed"

LEDGER_CREDIT = "credit"
LEDGER_DEBIT = "debit"
LEDGER_REVERSE = "reverse"
LEDGER_PAYOUT = "payout"

PAYOUT_PENDING = "pending_payout"
PAYOUT_PAID = "paid"
PAYOUT_REJECTED = "rejected"

# Campaign admin — balances / moderation (username without @)
CAMPAIGN_ADMIN_USERNAMES = frozenset({"acterichee"})

REJECT_REASONS = {
    "fake": "Подделка",
    "duplicate": "Дубликат операции",
    "unsupported": "Неподдерживаемый банк",
    "date": "Дата операции не подходит",
    "not_pdf": "Не исходный PDF",
    "not_original": "Не удалось подтвердить оригинальность",
    "terms": "Нарушение условий акции",
    "failed_op": "Операция не завершена",
    "outside_window": "Чек загружен вне периода акции",
    "manual": "Отклонено модератором",
}


def now_msk() -> datetime:
    return datetime.now(MSK)


def campaign_is_active(at: datetime | None = None) -> bool:
    ts = at or now_msk()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc).astimezone(MSK)
    else:
        ts = ts.astimezone(MSK)
    return CAMPAIGN_START <= ts <= CAMPAIGN_END


def campaign_has_ended(at: datetime | None = None) -> bool:
    ts = at or now_msk()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc).astimezone(MSK)
    else:
        ts = ts.astimezone(MSK)
    return ts > CAMPAIGN_END


def normalize_bank_key(key: str) -> str:
    return BANK_KEY_ALIASES.get((key or "").strip().lower(), "")


def is_campaign_admin(username: str | None, user_id: int = 0) -> bool:
    return (username or "").lower().lstrip("@") in CAMPAIGN_ADMIN_USERNAMES


def format_money_kopecks(kopecks: int) -> str:
    rub = kopecks // 100
    return f"{rub:,}".replace(",", " ") + " ₽"
