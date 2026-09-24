"""Telegram message layout for the bot ("card" design).

Pure functions: take already-computed facts, return Telegram HTML. Nothing
here touches the detector, so the look of every message can change in one
place without risking the verdict logic.

Card layout (Telegram HTML):

    <b>✅ Чек прошёл проверку</b>
    <i>file.pdf · 24.09.2026 23:25</i>

    <b>Платёж</b>
    <blockquote>Дата: 5 июля 2026, 11:52
    Сумма: <b>5 753 ₽</b>
    ...</blockquote>

    <b>Проверка</b>
    <blockquote>Банк: Т-Банк
    ...</blockquote>

    <b>История</b>
    <blockquote>24.09.2026 22:41 — @user</blockquote>
"""

from __future__ import annotations

import datetime
import html
import re

from detector.parser import _format_visibility

_MSK = datetime.timezone(datetime.timedelta(hours=3))

_MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
_MONTH_INDEX = {m: i + 1 for i, m in enumerate(_MONTHS_GEN)}

_NUM_DATE_RE = re.compile(
    r"\b(\d{2})\.(\d{2})\.(\d{4})"
    r"(?:\s*(?:г\.?|года)?[,\s]*(?:в\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
_WORD_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+(\d{4})"
    r"(?:\s*(?:г\.?|года)?[,\s]*(?:в\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
    re.IGNORECASE,
)
_FOOTER_RE = re.compile(
    r"генеральн\w*\s+лицензи|лицензия\s+банка|информация\s+в\s*справке\s+актуальна",
    re.IGNORECASE,
)

HEADERS = {
    "ok": "✅ Чек прошёл проверку",
    "fake": "❌ Чек не прошёл проверку",
    "failed": "⚠️ Перевод не выполнен",
    "unknown_bank": "❔ Банк не распознан",
    "unknown_doc": "❔ Не похоже на банковский чек",
}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


# ── field helpers ─────────────────────────────────────────────────────────────

def pretty_amount(raw: str | None) -> str | None:
    """'5 000,00 руб.' → '5 000 ₽'; '1 234,50 руб.' → '1 234,50 ₽'."""
    s = (raw or "").replace("\u00a0", " ").strip()
    if not s:
        return None
    m = re.search(r"(\d[\d\s]*)(?:[.,](\d{1,2}))?", s)
    if not m or not any(c.isdigit() for c in m.group(1)):
        return s
    whole = re.sub(r"\D", "", m.group(1))
    frac = (m.group(2) or "").rstrip("0")
    try:
        grouped = f"{int(whole):,}".replace(",", " ")
    except ValueError:
        return s
    if frac:
        grouped += "," + (m.group(2) or "")
    return grouped + " ₽"


def receipt_datetime(text: str) -> str | None:
    """Human date of the operation: '5 июля 2026, 11:52' (time optional)."""
    body = text or ""
    footer = _FOOTER_RE.search(body)
    if footer:
        body = body[: footer.start()]
    probe = body[:2500]

    found: list[tuple[datetime.date, str | None]] = []
    for m in _WORD_DATE_RE.finditer(probe):
        try:
            d = datetime.date(int(m.group(3)), _MONTH_INDEX[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            continue
        t = f"{int(m.group(4)):02d}:{m.group(5)}" if m.group(4) else None
        found.append((d, t))
    for m in _NUM_DATE_RE.finditer(probe):
        try:
            d = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        t = f"{int(m.group(4)):02d}:{m.group(5)}" if m.group(4) else None
        found.append((d, t))
    if not found:
        return None
    # Operation date is the newest date in the body; prefer a match with time.
    newest = max(d for d, _ in found)
    times = [t for d, t in found if d == newest and t]
    out = f"{newest.day} {_MONTHS_GEN[newest.month - 1]} {newest.year}"
    if times:
        out += f", {times[0]}"
    return out


def payment_rows(parsed: dict | None, text: str, *, show_status: bool) -> list[str]:
    """Rows for the «Платёж» section, already HTML-escaped."""
    parsed = parsed or {}
    show = _format_visibility(parsed)
    rows: list[str] = []

    when = receipt_datetime(text)
    if when:
        rows.append(f"Дата: {esc(when)}")

    amount = pretty_amount(parsed.get("amount"))
    if show["amount"] and amount:
        rows.append(f"Сумма: <b>{esc(amount)}</b>")

    sender = (parsed.get("sender") or "").strip()
    if show["sender"] and sender and sender != "—":
        rows.append(f"Отправитель: {esc(sender)}")
    sender_card = (parsed.get("sender_card") or "").strip()
    if show["sender_card"] and sender_card and sender_card != "—":
        rows.append(f"Карта отправителя: <code>{esc(sender_card)}</code>")

    receiver = (parsed.get("receiver") or "").strip()
    if receiver == "—":
        receiver = ""
    contact_label = (parsed.get("contact_label") or "").lower()
    contact_value = (parsed.get("contact_value") or "").strip()
    receiver_card = (parsed.get("receiver_card") or "").strip()
    card = ""
    phone = ""
    if show["contact"] and contact_value and contact_value != "—":
        if "телефон" in contact_label:
            phone = contact_value
        else:
            card = contact_value
    elif show["contact"] and receiver_card and receiver_card != "—":
        card = receiver_card

    if show["receiver"] and receiver and card:
        rows.append(f"Получатель: {esc(receiver)} · <code>{esc(card)}</code>")
    elif show["receiver"] and receiver:
        rows.append(f"Получатель: {esc(receiver)}")
    elif card:
        rows.append(f"Получатель: <code>{esc(card)}</code>")
    if phone:
        rows.append(f"Телефон: <code>{esc(phone)}</code>")

    account = (parsed.get("receiver_account") or "").strip()
    # T-Bank exposes only the last digits, which duplicate the masked card.
    redundant = bool(card) and len(re.sub(r"\D", "", account)) <= 4 and card.endswith(account)
    if show["receiver_account"] and account and account != "—" and not redundant:
        rows.append(f"Счёт получателя: <code>{esc(account)}</code>")

    rbank = (
        (parsed.get("recipient_bank_normalized") or "").strip()
        or ((parsed.get("fields") or {}).get("recipient_bank_normalized") or "").strip()
        or (parsed.get("receiver_bank") or "").strip()
    )
    if show["bank"] and rbank:
        rows.append(f"Банк получателя: {esc(rbank)}")

    status = (parsed.get("status") or "").strip()
    if show_status and show["status"] and status and status != "—":
        rows.append(f"Статус: {esc(status)}")
    return rows


# ── card ──────────────────────────────────────────────────────────────────────

def _section(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    return f"<b>{title}</b>\n<blockquote>" + "\n".join(rows) + "</blockquote>"


def result_card(
    *,
    kind: str,
    bank: str,
    filename: str,
    checked_at: datetime.datetime | None,
    parsed: dict | None,
    text: str,
    status: str = "",
    stale: bool = False,
    note: str = "",
    history: list[str] | None = None,
) -> str:
    """Assemble the whole result message.

    kind: 'ok' | 'fake' | 'failed' | 'unknown_bank' | 'unknown_doc'.
    note: extra human line under the «Проверка» section (already plain text).
    history: lines like '24.09.2026 22:41 — @user' (empty → section omitted).
    """
    checked_at = checked_at or datetime.datetime.now(tz=_MSK)
    stamp = checked_at.astimezone(_MSK).strftime("%d.%m.%Y %H:%M")
    meta = f"{esc(filename)} · {stamp}" if filename else stamp

    blocks: list[str] = [f"<b>{HEADERS.get(kind, HEADERS['ok'])}</b>\n<i>{meta}</i>"]

    if kind != "unknown_doc":
        rows = payment_rows(parsed, text, show_status=(kind in ("ok", "failed")))
        if kind == "failed" and status:
            rows = [r for r in rows if not r.startswith("Статус:")]
            rows.append(f"Статус: <b>{esc(status)}</b>")
        sec = _section("Платёж", rows)
        if sec:
            blocks.append(sec)

    check: list[str] = []
    if kind == "ok":
        if bank:
            check.append(f"Банк: {esc(bank)}")
        check.append("Структура документа: соответствует банку")
        check.append("Признаков изменения: нет")
        if stale:
            check.append("Дата чека: <b>старше 30 дней</b>")
    elif kind == "fake":
        if bank:
            check.append(f"Банк: {esc(bank)}")
        check.append("Структура документа: <b>не соответствует банку</b>")
        check.append("Признаков изменения: <b>есть</b>")
    elif kind == "failed":
        if bank:
            check.append(f"Банк: {esc(bank)}")
        check.append("Структура документа: соответствует банку")
        check.append("Операция: <b>не выполнена</b>")
    elif kind == "unknown_bank":
        check.append("Банк: <b>не поддерживается</b>")
    blocks.append(_section("Проверка", check))

    tail: list[str] = []
    if note:
        tail.append(esc(note))
    elif kind == "ok":
        tail.append("<i>Зачисление проверяйте в банке</i>")
    elif kind == "failed":
        tail.append("<i>Это не подтверждение оплаты</i>")
    elif kind == "unknown_bank":
        tail.append("<i>Список банков — кнопка «Проверяемые банки»</i>")
    if tail:
        blocks.append("\n".join(tail))

    if history:
        blocks.append(_section("История", [esc(h) for h in history]))

    return "\n\n".join(b for b in blocks if b)
