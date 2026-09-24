"""
PDF Checker Bot - Telegram bot for P2P traders.
Detects fake bank PDF receipts.
"""

import asyncio
import html
import logging
import os
import re
import datetime
import time
from collections import OrderedDict
from io import BytesIO

import fitz
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart, Command, Filter
from aiogram.types import TelegramObject, Update
from aiogram.types import (
    Message, Document, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    ChatMemberUpdated,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    MenuButtonCommands,
)
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramNetworkError
from dotenv import load_dotenv

from detector import route as route_bank
from detector.parser import parse as parse_receipt, format_receipt, parse_generic, parse_gazprombank
from detector import reputation
from detector import analytics
from detector.explain import build_user_explanation
import blocklist
import check_history
import ui
from campaign.config import (
    campaign_is_active,
    format_money_kopecks,
    is_campaign_admin,
)
from campaign import service as campaign_service

BLOCKED_TEXT = "⛔ <b>Доступ запрещён.</b>"

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")

# Optional proxy for local runs when Telegram is blocked (e.g. Hiddify mixed port).
_TELEGRAM_PROXY = (
    os.getenv("TELEGRAM_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("HTTP_PROXY")
    or ""
).strip()
if _TELEGRAM_PROXY:
    from aiogram.client.session.aiohttp import AiohttpSession
    bot = Bot(token=BOT_TOKEN, session=AiohttpSession(proxy=_TELEGRAM_PROXY))
    logging.info("Telegram proxy enabled")
else:
    bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

FREE_CHECKS_PER_DAY = 999         # effectively unlimited - free for now
STARS_PER_CHECK     = 1          # reserved for future monetization
ADMIN_IDS: set[int] = set(
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
)

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@acterichee")

# uid -> (date_str, count)  — resets automatically each calendar day
_user_checks: dict[int, tuple[str, int]] = {}

# Per-account concurrent PDF checks (in-flight). While at the cap, new uploads
# from the same Telegram user are rejected until a slot frees.
MAX_INFLIGHT_CHECKS_PER_USER = 3
_user_inflight: dict[int, int] = {}
_user_inflight_lock = asyncio.Lock()

# token -> (file_hash, opid, parsed_fields, pdf_bytes, bank_display_name, is_tbank)
# Bounded LRU: entries carry the full PDF, so an unbounded dict leaks memory on
# a long-running process. Oldest entries are evicted once the cap is reached.
_REPORT_CACHE_MAX = 300
_report_cache: OrderedDict[
    str, tuple[str, str | None, dict | None, bytes, str, bool]
] = OrderedDict()


def _report_cache_put(token: str, entry) -> None:
    _report_cache[token] = entry
    _report_cache.move_to_end(token)
    while len(_report_cache) > _REPORT_CACHE_MAX:
        _report_cache.popitem(last=False)


# Fire-and-forget background tasks must stay referenced until done, otherwise
# the event loop may garbage-collect them mid-flight.
_bg_tasks: set[asyncio.Task] = set()


def _spawn_bg(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


FAKE_THRESHOLD = 60
SUSPICIOUS_THRESHOLD = 25

REQUIRED_CHANNEL = "@proton_newss"
ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
ARCHIVE_CHANNEL = (os.getenv("ARCHIVE_CHANNEL", REQUIRED_CHANNEL) or "").strip()
ARCHIVE_SKIP_USERNAMES = frozenset({"kronlead", "acterichee"})


def _archive_target():
    if not ARCHIVE_ENABLED or not ARCHIVE_CHANNEL:
        return None
    if ARCHIVE_CHANNEL.lstrip("-").isdigit():
        try:
            return int(ARCHIVE_CHANNEL)
        except Exception:
            return None
    return ARCHIVE_CHANNEL


def _is_archive_chat(msg: Message) -> bool:
    target = _archive_target()
    if target is None:
        return False
    if isinstance(target, int):
        return msg.chat.id == target
    # target like @channel_name
    name = (msg.chat.username or "").lower()
    return bool(name and target.lstrip("@").lower() == name)


async def _archive_checked_pdf(
    msg: Message,
    doc: Document,
    pdf_bytes: bytes,
    *,
    bank: str,
    result: dict,
    file_hash: str,
) -> None:
    target = _archive_target()
    if target is None or _is_archive_chat(msg):
        return
    uname_raw = (msg.from_user.username or "").lower() if msg.from_user else ""
    if uname_raw in ARCHIVE_SKIP_USERNAMES:
        return
    verdict = result.get("verdict", "-")
    score = result.get("score", 0)
    uid = msg.from_user.id if msg.from_user else 0
    uname = f"@{msg.from_user.username}" if msg.from_user and msg.from_user.username else f"id:{uid}"
    flags = result.get("flags") or []
    first_flag = flags[0] if flags else "-"
    caption = (
        "🗂 <b>Архив проверки</b>\n"
        f"👤 {uname}\n"
        f"🏦 {_html_safe(bank or 'Неизвестный банк')}\n"
        f"📌 <b>{_html_safe(verdict)}</b> (score: {score})\n"
        f"🆔 <code>{file_hash[:16]}</code>\n"
        f"⚠️ {_html_safe(first_flag[:180])}"
    )
    try:
        await bot.send_document(
            chat_id=target,
            document=BufferedInputFile(pdf_bytes, filename=doc.file_name or "receipt.pdf"),
            caption=caption,
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("archive send failed")

def _yn(v: bool) -> str:
    return "Да" if v else "Нет"


async def _is_subscribed(user_id: int) -> bool:
    """Return True if user is a member of the required channel."""
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        # If we can't check (bot not admin in channel), allow through
        return True


async def _require_subscription(msg: Message) -> bool:
    """Send subscription gate if user is not subscribed. Returns True if blocked."""
    if await _is_subscribed(msg.from_user.id):
        return False
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться", url="https://t.me/proton_newss")],
        [InlineKeyboardButton(text="Готово", callback_data="check_sub")],
    ])
    await msg.answer(
        "<b>Нужна подписка на канал</b>\n"
        f"Бот бесплатный, взамен просим подписаться на {REQUIRED_CHANNEL}.\n\n"
        "<i>Подпишитесь и нажмите «Готово»</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return True

BTN_CHECK = "📄 Проверить чек"
BTN_BANKS = "🏦 Банки"
BTN_MAIL = "✉️ Почта"
BTN_SUPPORT = "💬 Поддержка"
BTN_PROFILE = "👤 Профиль"
# Labels from the previous keyboard; clients cache reply keyboards, so keep
# answering to them until every user has pressed something new.
_OLD_BTN_CHECK = "✅ Проверить чек"
_OLD_BTN_BANKS = "🏦 Проверяемые банки"
_OLD_BTN_MAIL = "📧 Почта"
_OLD_BTN_PROFILE = "👤 Мой профиль"


def _main_keyboard(user_id: int = 0, username: str | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_CHECK)],
        [KeyboardButton(text=BTN_BANKS), KeyboardButton(text=BTN_MAIL)],
        [KeyboardButton(text=BTN_SUPPORT), KeyboardButton(text=BTN_PROFILE)],
    ]
    if _is_privileged_user(username, user_id):
        rows.append([KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🛡 Админка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_CHECK)],
        [KeyboardButton(text=BTN_BANKS), KeyboardButton(text=BTN_MAIL)],
        [KeyboardButton(text=BTN_SUPPORT), KeyboardButton(text=BTN_PROFILE)],
    ],
    resize_keyboard=True,
)


def _kb_for(msg: Message) -> ReplyKeyboardMarkup:
    user = msg.from_user
    if not user:
        return MAIN_KEYBOARD
    return _main_keyboard(user.id, user.username)


def _user_stats(user_id: int) -> tuple[int, int, float | None]:
    """(checks, fakes found, first_seen ts) from the analytics DB."""
    try:
        con = analytics._con()
        try:
            total = con.execute(
                "SELECT COUNT(*) FROM checks WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            fakes = con.execute(
                "SELECT COUNT(*) FROM checks WHERE user_id = ? AND verdict = 'ФЕЙК'",
                (user_id,),
            ).fetchone()[0]
            row = con.execute(
                "SELECT first_seen FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            first = float(row[0]) if row and row[0] else None
        finally:
            con.close()
        return int(total or 0), int(fakes or 0), first
    except Exception:
        logging.exception("user stats failed")
        return 0, 0, None


def _profile_text(user_id: int, username: str | None) -> str:
    uname = f"@{username}" if username else "-"
    total, fakes, first = _user_stats(user_id)
    rows = [
        f"ID: <code>{user_id}</code>",
        f"Username: {_html_safe(uname)}",
        f"Проверок: <b>{total}</b>",
        f"Подделок найдено: <b>{fakes}</b>",
    ]
    if first:
        rows.append(f"С нами с: {ui.human_date(first)}")
    return "👤 <b>Профиль</b>\n<blockquote>" + "\n".join(rows) + "</blockquote>"


def _today() -> str:
    return datetime.date.today().isoformat()

def _checks_used(uid: int) -> int:
    entry = _user_checks.get(uid)
    if entry and entry[0] == _today():
        return entry[1]
    return 0

def _checks_left(uid: int) -> int:
    return max(0, FREE_CHECKS_PER_DAY - _checks_used(uid))

def _use_check(uid: int) -> bool:
    if _checks_left(uid) <= 0:
        return False
    _user_checks[uid] = (_today(), _checks_used(uid) + 1)
    return True


# Statuses that mean the transfer did NOT go through — structurally the PDF may
# be genuine, but the payment itself failed, so it must never be accepted.
_FAILED_STATUSES = {
    "неуспешно", "неуспешная", "не выполнен", "не выполнено",
    "отклонен", "отклонено", "отклонена", "отклонён",
    "ошибка", "отменен", "отменено", "отменена", "отменён",
    "failed", "rejected", "cancelled", "canceled", "error",
}


def _status_failed(status: str) -> bool:
    s = (status or "").lower().strip()
    return any(w in s for w in _FAILED_STATUSES)


def _operation_failed(status: str, result: dict | None = None) -> bool:
    """Transfer did not complete — never present as a successful original."""
    if _status_failed(status):
        return True
    result = result or {}
    details = result.get("details") or {}
    if str(details.get("operation_status_class") or "") == "FAILED_FINAL":
        return True
    notice = (
        result.get("status_notice")
        or details.get("status_warning")
        or ""
    ).lower()
    if "перевод не выполнен" in notice or "не подтверждение оплаты" in notice:
        return True
    return _status_failed(notice)


def _receipt_body(pdf_bytes: bytes, bank: str, is_tbank: bool) -> tuple[str, str, str]:
    """Return (formatted_fields, title, status) for a genuine receipt of any bank."""
    parsed, title = _receipt_parsed(pdf_bytes, bank, is_tbank)
    return format_receipt(parsed), title, parsed.get("status", "")


def _receipt_parsed(pdf_bytes: bytes, bank: str, is_tbank: bool) -> tuple[dict, str]:
    """Structured receipt fields (bank-aware) plus a display title."""
    if is_tbank:
        parsed = parse_receipt(pdf_bytes)
        title = parsed.get("title") or f"Чек {bank}"
    elif bank and "газпром" in bank.lower():
        parsed = parse_gazprombank(pdf_bytes)
        title = parsed.get("title") or f"Чек {bank}"
    else:
        parsed = parse_generic(pdf_bytes)
        title = f"Чек {bank}"
    # Issuer is the routed bank that formed the receipt; never overwrite recipient.
    parsed["issuer_bank"] = bank or parsed.get("issuer_bank") or ""
    fields = dict(parsed.get("fields") or {})
    fields["issuer_bank"] = parsed["issuer_bank"]
    # Recipient bank must already come from explicit PDF field extraction.
    fields.setdefault("recipient_bank_raw", parsed.get("recipient_bank_raw") or "")
    fields.setdefault(
        "recipient_bank_normalized",
        parsed.get("recipient_bank_normalized") or "",
    )
    fields.setdefault(
        "recipient_bank_source",
        parsed.get("recipient_bank_source") or "",
    )
    parsed["fields"] = fields
    parsed["recipient_bank_normalized"] = fields.get("recipient_bank_normalized") or ""
    return parsed, title


_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_DATE_WORD_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)
_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _is_stale_receipt(pdf_bytes: bytes, *, days: int = 30) -> bool:
    """True if the receipt operation/issue date is older than `days` (default 1 month).

    Ignores bank-license / footer dates (e.g. «Генеральная лицензия … 17.02.2015»)
    that otherwise win over word-form dates like «20 июля 2026».
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
    except Exception:
        return False
    text = text or ""

    # Drop license / disclaimer tails before scanning dates.
    footer = re.search(
        r"генеральн\w*\s+лицензи|лицензия\s+банка|информация\s+в\s*справке\s+актуальна",
        text,
        re.IGNORECASE,
    )
    body = text[: footer.start()] if footer else text
    probe = body[:2000]

    candidates: list[datetime.date] = []
    for mw in _DATE_WORD_RE.finditer(probe):
        try:
            month = _RU_MONTHS.get(mw.group(2).lower())
            if month:
                candidates.append(
                    datetime.date(int(mw.group(3)), month, int(mw.group(1)))
                )
        except Exception:
            pass
    for m in _DATE_RE.finditer(probe):
        try:
            candidates.append(
                datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            )
        except Exception:
            pass

    if not candidates:
        return False

    # Operation / issue date is the newest date in the receipt body.
    d = max(candidates)
    return (datetime.date.today() - d).days > days


VERBOSE_USERNAMES = frozenset({"kronlead"})


def _is_privileged_user(username: str | None, user_id: int = 0) -> bool:
    """@kronlead и ADMIN_IDS — подробные ответы и /stats."""
    return user_id in ADMIN_IDS or (username or "").lower() in VERBOSE_USERNAMES


def _is_user_blocked(user_id: int = 0, username: str | None = None) -> bool:
    if _is_privileged_user(username, user_id):
        return False
    return blocklist.is_blocked(user_id, username)


class BlocklistMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if isinstance(event, Update):
            if event.message and event.message.from_user:
                user = event.message.from_user
            elif event.callback_query and event.callback_query.from_user:
                user = event.callback_query.from_user
            elif event.pre_checkout_query and event.pre_checkout_query.from_user:
                user = event.pre_checkout_query.from_user
        if user and _is_user_blocked(user.id, user.username):
            if isinstance(event, Update):
                if event.message:
                    await event.message.answer(
                        _blocked_user_text(user.id, user.username),
                        parse_mode="HTML",
                    )
                elif event.callback_query:
                    await event.callback_query.answer(
                        _blocked_user_plain(user.id, user.username)[:200],
                        show_alert=True,
                    )
                elif event.pre_checkout_query:
                    await bot.answer_pre_checkout_query(
                        event.pre_checkout_query.id, ok=False,
                        error_message="Доступ запрещён.",
                    )
            return
        return await handler(event, data)


dp.update.middleware(BlocklistMiddleware())


async def _acquire_user_check_slot(user_id: int) -> bool:
    """Reserve one in-flight check slot. False if user is already at the cap."""
    if user_id <= 0:
        return True
    async with _user_inflight_lock:
        current = _user_inflight.get(user_id, 0)
        if current >= MAX_INFLIGHT_CHECKS_PER_USER:
            return False
        _user_inflight[user_id] = current + 1
        return True


async def _release_user_check_slot(user_id: int) -> None:
    if user_id <= 0:
        return
    async with _user_inflight_lock:
        current = _user_inflight.get(user_id, 0)
        if current <= 1:
            _user_inflight.pop(user_id, None)
        else:
            _user_inflight[user_id] = current - 1


def _is_verbose_user(username: str | None, user_id: int = 0) -> bool:
    return _is_privileged_user(username, user_id)


def _html_safe(text: str) -> str:
    """Экранировать динамический текст для parse_mode=HTML."""
    return html.escape(text or "", quote=False)


def _normalize_binary_result(result: dict) -> dict:
    """External verdict: fake, clean, or unknown document.

    Engine verdict / known_fake_count / hard_count take priority over score.
    Never demote ФЕЙК to ЧИСТО because score < FAKE_THRESHOLD.
    """
    details = result.get("details") or {}
    verdict = str(result.get("verdict", "")).upper()

    if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ" or result.get("verdict") == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ":
        result["verdict"] = "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
        result["emoji"] = "⚪"
        return result

    # Classifier said «Sber» but engine rejected the receipt shape — not a fake Sber.
    if any("NOT_SBER_RECEIPT" in str(f) for f in (result.get("flags") or [])):
        result["verdict"] = "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
        result["emoji"] = "⚪"
        result["score"] = 0
        return result

    decisive = (
        result.get("verdict") == "ФЕЙК"
        or verdict == "ФЕЙК"
        or int(details.get("hard_count") or 0) > 0
        or int(details.get("known_fake_count") or 0) > 0
        or any(
            "KNOWN" in str(f).upper() or "VTB_KNOWN_" in str(f).upper()
            for f in (result.get("flags") or [])
        )
        or int(result.get("score") or 0) >= FAKE_THRESHOLD
    )

    if decisive:
        result["verdict"] = "ФЕЙК"
        result["emoji"] = "🔴"
        result["score"] = max(int(result.get("score") or 0), 95)
        details = dict(result.get("details") or {})
        details["verdict_after_normalization"] = "ФЕЙК"
        result["details"] = details
        return result

    result["verdict"] = "ЧИСТО"
    result["emoji"] = "✅"
    result["score"] = 0
    details = dict(result.get("details") or {})
    details["verdict_after_normalization"] = "ЧИСТО"
    result["details"] = details
    return result


def _verdict_bank_suffix(bank: str | None, recognized: bool) -> str:
    if recognized and bank:
        return f" ({_html_safe(bank)})"
    return ""



TG_MESSAGE_LIMIT = 4000
_TG_HTML_CLOSEABLE = frozenset({
    "b", "i", "u", "s", "code", "pre", "a", "tg-spoiler", "blockquote",
})


def _close_open_html_tags(text: str) -> str:
    """Append missing closers so Telegram HTML parse_mode accepts truncated text."""
    stack: list[str] = []
    for m in re.finditer(r"</?([a-zA-Z0-9\-]+)(?:\s[^>]*)?/?>", text or ""):
        raw = m.group(0)
        name = m.group(1).lower()
        if name not in _TG_HTML_CLOSEABLE:
            continue
        if raw.startswith("</"):
            if stack and stack[-1] == name:
                stack.pop()
            continue
        if raw.endswith("/>"):
            continue
        stack.append(name)
    if not stack:
        return text or ""
    return (text or "") + "".join(f"</{name}>" for name in reversed(stack))


def _truncate_tg_message(text: str, limit: int = TG_MESSAGE_LIMIT) -> str:
    """Truncate for Telegram without leaving unclosed HTML tags (e.g. bare <i>)."""
    text = text or ""
    if len(text) <= limit:
        return text
    marker = "\n\n… (сообщение обрезано)"
    keep = max(0, limit - len(marker))
    cut = text[:keep].rstrip()
    # Drop a partial tag at the cut boundary: "...<i>foo" / "...<b"
    last_lt = cut.rfind("<")
    last_gt = cut.rfind(">")
    if last_lt > last_gt:
        cut = cut[:last_lt].rstrip()
    cut = _close_open_html_tags(cut)
    # Closing tags may push over the limit — shrink and re-close.
    guard = 0
    while len(cut) + len(marker) > limit and cut and guard < 8:
        guard += 1
        overflow = len(cut) + len(marker) - limit
        cut = cut[: max(0, len(cut) - overflow - 8)].rstrip()
        last_lt = cut.rfind("<")
        last_gt = cut.rfind(">")
        if last_lt > last_gt:
            cut = cut[:last_lt].rstrip()
        cut = _close_open_html_tags(cut)
    return cut + marker


async def _tg_call(label: str, factory, *, retries: int = 4, base_delay: float = 0.4):
    """Retry transient Telegram/aiohttp disconnects (common during bot restarts)."""
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            return await factory()
        except TelegramNetworkError as exc:
            last = exc
            logging.warning("%s network error (try %s/%s): %s", label, attempt + 1, retries, exc)
        except (ConnectionError, TimeoutError, OSError) as exc:
            last = exc
            logging.warning("%s transport error (try %s/%s): %s", label, attempt + 1, retries, exc)
        if attempt + 1 < retries:
            await asyncio.sleep(base_delay * (2 ** attempt))
    assert last is not None
    raise last


async def _edit_status_text(status_msg, text: str, **kwargs):
    """Edit with Telegram 4096-char safety + HTML entity fallback."""
    safe = _truncate_tg_message(text)
    try:
        await _tg_call("edit_status", lambda: status_msg.edit_text(safe, **kwargs))
    except Exception as exc:
        err = str(exc).lower()
        # Fallback without parse_mode / markup if still rejected.
        if "message_too_long" in err or "msg_too_long" in err:
            await _tg_call(
                "edit_status_short",
                lambda: status_msg.edit_text(_truncate_tg_message(safe, 3500)),
            )
            return
        if "can't parse entities" in err or "parse entities" in err:
            plain = re.sub(r"<[^>]+>", "", safe)
            plain = html.unescape(plain)
            kw = {k: v for k, v in kwargs.items() if k != "parse_mode"}
            await _tg_call(
                "edit_status_plain",
                lambda: status_msg.edit_text(_truncate_tg_message(plain), **kw),
            )
            return
        raise

def _format_result(pdf_bytes: bytes, result: dict, bank: str, is_tbank: bool,
                   seen_before: bool, *, username: str | None = None,
                   user_id: int = 0, text: str = "", filename: str = "",
                   history: list[str] | None = None) -> str:
    score = result["score"]
    flags = result["flags"]
    verbose = _is_verbose_user(username, user_id)

    recognized = bank not in (None, "", "Неизвестный банк")
    is_unknown_doc = result.get("verdict") == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
    is_fake = result.get("verdict") == "ФЕЙК" or score >= FAKE_THRESHOLD
    status_notice = result.get("status_notice") or (result.get("details") or {}).get("status_warning", "")
    expl = build_user_explanation(result)

    body, title, status = "", f"Чек {bank}", ""
    parsed: dict | None = None
    if recognized or is_tbank:
        try:
            parsed, title = _receipt_parsed(pdf_bytes, bank, is_tbank)
            body = format_receipt(parsed)
            status = parsed.get("status", "")
        except Exception:
            pass
    elif not is_unknown_doc:
        try:
            parsed = parse_generic(pdf_bytes, text)
        except Exception:
            parsed = None

    stale = _is_stale_receipt(pdf_bytes)
    if not verbose:
        if not text:
            try:
                pdoc = fitz.open(stream=pdf_bytes, filetype="pdf")
                text = "".join(p.get_text() for p in pdoc)
                pdoc.close()
            except Exception:
                text = ""
        note = ""
        if is_unknown_doc:
            kind = "unknown_doc"
            note = (result.get("user_message") or result.get("summary") or "").strip()
        elif is_fake:
            kind = "fake"
            note = (result.get("custom_message") or "").strip()
        elif not recognized:
            kind = "unknown_bank"
        elif _operation_failed(status, result):
            kind = "failed"
        else:
            kind = "ok"
            if status_notice:
                note = status_notice
        return ui.result_card(
            kind=kind,
            bank=bank if recognized else "",
            filename=filename,
            checked_at=datetime.datetime.now(tz=datetime.timezone.utc),
            parsed=parsed,
            text=text,
            status=status,
            stale=stale,
            note=note,
            history=history or [],
        )

    # Подробный режим — только @kronlead
    details = result.get("details") or {}
    if is_tbank and details.get("engine") == "tbank_v6":
        expert = details.get("expert_report") or {}
        body_lines = expert.get("body_lines") or []
        if is_fake:
            custom = (result.get("custom_message") or "").strip()
            if custom:
                return _html_safe(custom)
            # @kronlead: lead with HARD/KNOWN expert body (bypass + why-not-variability).
            # Soft "простым языком" only if expert_report missing.
            summary = expert.get("summary") or expl.get("summary") or "ФЕЙК"
            lines = [f"❌ <b>{_html_safe(summary)}</b>", ""]
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:56]]
                if len(body_lines) > 57:
                    lines.append(f"… ещё {len(body_lines) - 57} строк в expert_report")
            else:
                if expl.get("reasons"):
                    lines.append("<b>Почему простым языком:</b>")
                    lines += [f"• {_html_safe(r)}" for r in expl["reasons"][:6]]
                    lines.append("")
                if flags:
                    lines += ["", "<b>Технически:</b>"] + [
                        f"• {_html_safe(f)}" for f in flags[:12]
                    ]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("receipt_subtype_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_alfa_engine = details.get("engine") in {"alfa_v1", "alfa_v2"} or bool(
        details.get("alfa_v1_shadow")
    )
    if is_alfa_engine:
        expert = details.get("expert_report") or {}
        if not expert.get("body_lines") and details.get("alfa_v1_shadow"):
            expert = (details["alfa_v1_shadow"].get("v1_expert_report") or {})
        body_lines = expert.get("body_lines") or []
        hard_flags = details.get("hard_flags") or flags or []
        meta_line = (
            f"<i>engine={_html_safe(str(details.get('engine') or ''))} "
            f"version={_html_safe(str(details.get('version') or details.get('validator_version') or ''))} "
            f"rollout_mode={_html_safe(str(details.get('rollout_mode') or 'full'))} "
            f"verdict={_html_safe(str(details.get('final_verdict') or expl.get('verdict') or ''))}</i>"
        )
        if is_fake:
            lines = [f"❌ <b>{_html_safe(expert.get('summary', expl['summary']))}</b>", "", meta_line, ""]
            if body_lines:
                # Cap verbose body — full atlas dumps blow past TG 4096 and used to
                # truncate mid-<i>, which Telegram rejects as bad HTML entities.
                lines += [_html_safe(ln) for ln in body_lines[1:36]]
                if len(body_lines) > 37:
                    lines.append(f"… ещё {len(body_lines) - 37} строк в expert_report")
            if hard_flags:
                lines += ["", "<b>hard_flags:</b>"] + [
                    f"• {_html_safe(f)}" for f in hard_flags[:6]
                ]
            elif flags:
                lines += ["", "<b>Технически:</b>"] + [
                    f"• {_html_safe(f)}" for f in flags[:12]
                ]
            if expl.get("recommendation"):
                lines += ["", f"<i>{_html_safe(expl['recommendation'])}</i>"]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("receipt_subtype_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        lines += ["", meta_line]
        if hard_flags:
            lines += ["<b>hard_flags:</b>"] + [f"• {_html_safe(f)}" for f in hard_flags[:4]]
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_sber_engine = (
        details.get("engine") in {"sber_v1", "sber_v2"}
        or bool(details.get("sber_v1_shadow"))
    )
    if is_sber_engine:
        expert = details.get("expert_report") or {}
        if not expert.get("body_lines") and details.get("sber_v1_shadow"):
            expert = (details["sber_v1_shadow"].get("v1_expert_report") or {})
        body_lines = expert.get("body_lines") or []
        shadow = details.get("sber_v1_shadow") or {}
        if is_fake:
            # @kronlead: HARD/KNOWN expert body first (bypass + why-not-variability).
            summary = expert.get("summary") or expl.get("summary") or "ФЕЙК"
            lines = [f"❌ <b>{_html_safe(summary)}</b>", ""]
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:56]]
                if len(body_lines) > 57:
                    lines.append(f"… ещё {len(body_lines) - 57} строк в expert_report")
            else:
                if expl.get("reasons"):
                    lines.append("<b>Почему простым языком:</b>")
                    lines += [f"• {_html_safe(r)}" for r in expl["reasons"][:6]]
                    lines.append("")
                if flags:
                    lines += ["", "<b>Технически:</b>"] + [
                        f"• {_html_safe(f)}" for f in flags[:12]
                    ]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("submethod_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines[:40]]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_ozon_v1 = (
        details.get("engine") == "ozon_v1"
        or bool(details.get("ozon_v1_shadow"))
    )
    if is_ozon_v1:
        expert = details.get("expert_report") or {}
        if not expert.get("body_lines") and details.get("ozon_v1_shadow"):
            expert = (details["ozon_v1_shadow"].get("v1_expert_report") or {})
        body_lines = expert.get("body_lines") or []
        shadow = details.get("ozon_v1_shadow") or {}
        if is_fake:
            lines = [f"❌ <b>{_html_safe(expert.get('summary', expl['summary']))}</b>", ""]
            if shadow.get("mode") == "shadow":
                lines.append(
                    f"<i>Shadow v1: {_html_safe(str(shadow.get('v1_verdict')))} "
                    f"| legacy: {_html_safe(str(shadow.get('legacy_verdict')))}</i>"
                )
                lines.append("")
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:]]
            elif flags:
                lines += ["", "<b>Технически:</b>"] + [
                    f"• {_html_safe(f)}" for f in flags[:12]
                ]
            if expl.get("recommendation"):
                lines += ["", f"<i>{_html_safe(expl['recommendation'])}</i>"]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("family_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_vtb = (
        details.get("engine") in {"vtb_v1", "vtb_v2"}
        or bool(details.get("vtb_v1_shadow"))
        or bool(details.get("vtb_v2_shadow"))
        or str(details.get("engine") or "").startswith("vtb")
    )
    if is_vtb:
        expert = details.get("expert_report") or {}
        if not expert.get("body_lines") and details.get("vtb_v1_shadow"):
            expert = (details["vtb_v1_shadow"].get("v1_expert_report") or {})
        if not expert.get("body_lines") and details.get("vtb_v2_shadow"):
            expert = (details["vtb_v2_shadow"].get("v2_expert_report") or {})
        body_lines = expert.get("body_lines") or []
        shadow = details.get("vtb_v2_shadow") or details.get("vtb_v1_shadow") or {}
        if is_fake:
            lines = [f"❌ <b>{_html_safe(expert.get('summary', expl['summary']))}</b>", ""]
            if shadow.get("mode") == "shadow":
                lines.append(
                    f"<i>Shadow: {_html_safe(str(shadow.get('v2_verdict') or shadow.get('v1_verdict')))}</i>"
                )
                lines.append("")
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:]]
            elif flags:
                lines += ["", "<b>Технически:</b>"] + [
                    f"• {_html_safe(f)}" for f in flags[:12]
                ]
            if expl.get("recommendation"):
                lines += ["", f"<i>{_html_safe(expl['recommendation'])}</i>"]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("submethod_label") or details.get("family_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_gpb_v1 = (
        details.get("engine") == "gpb_v1"
        or bool(details.get("gpb_v1_shadow"))
    )
    if is_gpb_v1:
        expert = details.get("expert_report") or {}
        if not expert.get("body_lines") and details.get("gpb_v1_shadow"):
            expert = (details["gpb_v1_shadow"].get("v1_expert_report") or {})
        body_lines = expert.get("body_lines") or []
        shadow = details.get("gpb_v1_shadow") or {}
        if is_fake:
            lines = [f"❌ <b>{_html_safe(expert.get('summary', expl['summary']))}</b>", ""]
            if shadow.get("mode") == "shadow":
                lines.append(
                    f"<i>Shadow v1: {_html_safe(str(shadow.get('v1_verdict')))} "
                    f"| legacy: {_html_safe(str(shadow.get('legacy_verdict')))}</i>"
                )
                lines.append("")
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:]]
            elif flags:
                lines += ["", "<b>Технически:</b>"] + [
                    f"• {_html_safe(f)}" for f in flags[:12]
                ]
            if expl.get("recommendation"):
                lines += ["", f"<i>{_html_safe(expl['recommendation'])}</i>"]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("family_label")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    is_sparse9_v1 = details.get("engine") == "sparse9_v1"
    if is_sparse9_v1:
        expert = details.get("expert_report") or {}
        body_lines = expert.get("body_lines") or []
        if is_fake:
            lines = [f"❌ <b>{_html_safe(expert.get('summary', expl['summary']))}</b>", ""]
            if body_lines:
                lines += [_html_safe(ln) for ln in body_lines[1:]]
            elif flags:
                lines += ["", "<b>Технически:</b>"] + [
                    f"• {_html_safe(f)}" for f in flags[:12]
                ]
            if expl.get("recommendation"):
                lines += ["", f"<i>{_html_safe(expl['recommendation'])}</i>"]
            return "\n".join(lines)

        lines = []
        if body:
            lines += [f"<code>{_html_safe(body)}</code>", ""]
        subtype = details.get("method") or details.get("bank_display")
        display_title = subtype or title
        if _operation_failed(status, result):
            lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
            return "\n".join(lines)
        if body_lines:
            lines += [_html_safe(ln) for ln in body_lines]
        else:
            lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
        if stale:
            lines.append("⚠️ <b>Устаревший чек</b>")
        return "\n".join(lines)

    if is_fake:
        lines = [f"❌ <b>{_html_safe(expl['summary'])}</b>", ""]
        if expl["reasons"]:
            lines.append("<b>Почему:</b>")
            lines += [f"• {_html_safe(r)}" for r in expl["reasons"]]
            lines.append("")
        lines.append(f"<i>{_html_safe(expl['recommendation'])}</i>")
        if flags:
            lines += ["", "<b>Технически:</b>"] + [f"• {_html_safe(f)}" for f in flags[:12]]
        return "\n".join(lines)

    if not recognized:
        lines = ["❓ <b>Чек не распознан</b>", "",
                 "<i>Банк или формат чека нам неизвестен.</i>"]
        if expl["reasons"]:
            lines += ["", "<b>Замечания:</b>"] + [f"• {_html_safe(r)}" for r in expl["reasons"]]
        if flags:
            lines += ["", "<b>Технически:</b>"] + [f"  • {_html_safe(f)}" for f in flags]
        return "\n".join(lines)

    lines = []
    if body:
        lines += [f"<code>{_html_safe(body)}</code>", ""]
    subtype = (result.get("details") or {}).get("receipt_subtype_label")
    display_title = subtype or title
    if _operation_failed(status, result):
        lines.append(f"❌ <b>Перевод не выполнен (статус: {_html_safe(status)})</b>")
        lines.append("")
        lines.append("<i>Операция не прошла - деньги не были переведены.</i>")
        return "\n".join(lines)

    lines.append(f"✅ <b>{_html_safe(display_title)}</b>")
    if stale:
        lines.append("⚠️ <b>Устаревший чек</b>")
    if expl.get("recommendation"):
        lines.append("")
        lines.append(f"<i>{_html_safe(expl['recommendation'])}</i>")
    return "\n".join(lines)


# ── Handlers ─────────────────────────────────────────────────────────────────

WELCOME_CAPTION = (
    "<b>PROTON</b> - проверка банковских чеков на подлинность\n\n"
    "<b>Как проверить</b>\n"
    "<blockquote>1. Получите PDF-чек от контрагента\n"
    "2. Отправьте файл сюда\n"
    "3. Результат придёт через несколько секунд</blockquote>\n\n"
    "Письмо от банка тоже можно проверить - раздел «Почта».\n\n"
    "<blockquote expandable><b>Условия использования</b>\n"
    "1. Запрещено использовать бота для тестирования программ подделки чеков. "
    "При выявлении - блокировка.\n"
    "2. Мы не несём ответственности за результаты проверок. Все результаты носят "
    "информационный характер и не гарантируют 100% точность.\n"
    "Используя PROTON, вы подтверждаете согласие с правилами.</blockquote>\n\n"
    f"<i>Поддержка: {SUPPORT_USERNAME}</i>"
)

GROUP_INTRO = (
    "<b>PROTON подключён</b>\n"
    "Каждый PDF-чек в этом чате будет проверен автоматически, ответ придёт под файлом.\n\n"
    "<blockquote>Назначьте бота <b>администратором</b>, иначе он не увидит файлы</blockquote>\n\n"
    f"<i>Бесплатно · {SUPPORT_USERNAME}</i>"
)


@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(cb: CallbackQuery):
    if await _is_subscribed(cb.from_user.id):
        await cb.message.delete()
        await cb.message.answer(
            WELCOME_CAPTION,
            parse_mode="HTML",
            reply_markup=_main_keyboard(cb.from_user.id, cb.from_user.username),
        )
        await cb.answer()
    else:
        await cb.answer("Подписка не найдена. Подпишитесь и нажмите «Готово» ещё раз.", show_alert=True)


@dp.message(CommandStart())
async def cmd_start(msg: Message):
    if msg.from_user:
        analytics.touch_user(
            msg.from_user.id,
            username=msg.from_user.username,
            first_name=msg.from_user.first_name,
            last_name=msg.from_user.last_name,
        )
    if msg.chat.type in ("group", "supergroup"):
        await msg.answer(GROUP_INTRO, parse_mode="HTML")
        return
    if await _require_subscription(msg):
        return
    uid = msg.from_user.id if msg.from_user else 0
    uname = msg.from_user.username if msg.from_user else None
    await msg.answer(
        WELCOME_CAPTION,
        parse_mode="HTML",
        reply_markup=_main_keyboard(uid, uname),
    )


@dp.my_chat_member()
async def on_added_to_chat(event: ChatMemberUpdated):
    """Greet the group with usage instructions when the bot is added."""
    if event.chat.type not in ("group", "supergroup"):
        return
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    added = old_status in ("left", "kicked") and new_status in ("member", "administrator")
    if added:
        try:
            await bot.send_message(event.chat.id, GROUP_INTRO, parse_mode="HTML")
        except Exception:
            logging.exception("failed to greet group")


@dp.message(Command("check"), F.chat.type == "private")
@dp.message(F.text.in_({BTN_CHECK, _OLD_BTN_CHECK}), F.chat.type == "private")
async def btn_check(msg: Message):
    if await _require_subscription(msg):
        return
    await msg.answer(
        "<b>Пришлите PDF-чек</b>\n"
        "<blockquote>В приложении банка: чек → «Поделиться» → PDF\n"
        "Скриншоты и фото не проверяются</blockquote>\n\n"
        "<i>Письмо от банка - через раздел «Почта»</i>",
        parse_mode="HTML",
        reply_markup=_kb_for(msg),
    )


@dp.message(Command("banks"), F.chat.type == "private")
@dp.message(F.text.in_({BTN_BANKS, _OLD_BTN_BANKS}), F.chat.type == "private")
async def btn_banks(msg: Message):
    from detector.profiles import format_banks_list_html
    body = format_banks_list_html()
    await msg.answer(
        "🏦 <b>Проверяемые банки</b>\n\n" + body + "\n\n"
        "<i>Чек банка не из списка получит ответ «Банк не распознан»</i>",
        parse_mode="HTML",
        reply_markup=_kb_for(msg),
    )


@dp.message(Command("mail"), F.chat.type == "private")
@dp.message(F.text.in_({BTN_MAIL, _OLD_BTN_MAIL}), F.chat.type == "private")
async def btn_email(msg: Message):
    from detector import mailbox
    addrs = mailbox.addresses_for(msg.chat.id, msg.from_user.username if msg.from_user else None)
    if addrs:
        body = "\n".join(f"<code>{_html_safe(a)}</code>" for a in addrs)
        addr_title = "Ваш адрес" if len(addrs) == 1 else "Ваши адреса"
        text = (
            "<b>Проверка по почте</b>\n"
            "Самый надёжный способ: письмо отправляет сервер банка, "
            "подпись проверяется криптографически.\n\n"
            f"<b>{addr_title}</b>\n"
            f"<blockquote>{body}</blockquote>\n\n"
            "<b>Как проверить</b>\n"
            "<blockquote>1. Контрагент в приложении банка: чек → «На e-mail»\n"
            "2. Указывает ваш адрес\n"
            "3. Результат приходит сюда сам</blockquote>"
        )
    else:
        text = (
            "<b>Проверка по почте</b>\n"
            "<i>Функция настраивается. Скоро здесь появится ваш персональный "
            "адрес для проверки чеков из писем банка.</i>"
        )
    await msg.answer(text, parse_mode="HTML", reply_markup=_kb_for(msg))


@dp.message(Command("support"), F.chat.type == "private")
@dp.message(F.text == BTN_SUPPORT, F.chat.type == "private")
async def btn_support(msg: Message):
    await msg.answer(
        "<b>Поддержка</b>\n"
        f"Вопросы, сотрудничество и спорные чеки: {SUPPORT_USERNAME}\n\n"
        "<i>К обращению приложите PDF, о котором идёт речь</i>",
        parse_mode="HTML",
        reply_markup=_kb_for(msg),
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    from detector.profiles import format_banks_list_html
    banks = format_banks_list_html()
    await msg.answer(
        "<b>Как пользоваться</b>\n"
        "<blockquote>1. Получите PDF-чек от контрагента\n"
        "2. Отправьте файл сюда\n"
        "3. Результат придёт через несколько секунд</blockquote>\n\n"
        "<b>Проверка по почте</b>\n"
        "Нажмите «Почта» и попросите контрагента отправить чек из приложения банка "
        "на ваш адрес. Письмо шлёт сам банк, подпись проверяется криптографически.\n\n"
        f"<b>Проверяемые банки</b>\n<blockquote expandable>{banks}</blockquote>\n\n"
        "<i>Все проверки бесплатны</i>",
        parse_mode="HTML",
    )


@dp.message(Command("balance"))
async def cmd_balance(msg: Message):
    left = _checks_left(msg.from_user.id)
    await msg.answer(
        f"💳 Осталось бесплатных проверок сегодня: <b>{left}/{FREE_CHECKS_PER_DAY}</b>",
        parse_mode="HTML",
    )


def _blocked_user_plain(user_id: int, username: str | None) -> str:
    reason = blocklist.block_reason(user_id, username)
    if reason:
        return "Вы заблокированы.\n\n" + reason
    return "Вы заблокированы."


def _blocked_user_text(user_id: int, username: str | None) -> str:
    reason = blocklist.block_reason(user_id, username)
    text = "⛔ <b>Вы заблокированы.</b>"
    if reason:
        text += "\n\n" + html.escape(reason)
    return text


_ADMIN_WAIT: dict[int, dict] = {}


def _admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="adm:block")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="adm:unblock")],
        [InlineKeyboardButton(text="📋 Список", callback_data="adm:list")],
    ])


def _parse_block_target(raw: str) -> tuple[int, str]:
    target = (raw or "").strip()
    if target.isdigit():
        return int(target), ""
    return 0, target


class _AdminWizardFilter(Filter):
    async def __call__(self, msg: Message) -> bool:
        user = msg.from_user
        if not user or not _is_privileged_user(user.username, user.id):
            return False
        return user.id in _ADMIN_WAIT


@dp.message(_AdminWizardFilter())
async def admin_wizard(msg: Message):
    user = msg.from_user
    state = _ADMIN_WAIT.get(user.id) or {}
    text = (msg.text or "").strip()
    if text.lower() in {"отмена", "/cancel", "отменить"}:
        _ADMIN_WAIT.pop(user.id, None)
        await msg.answer("Отменено.", reply_markup=_kb_for(msg))
        return
    if text == "🛡 Админка":
        _ADMIN_WAIT.pop(user.id, None)
        await msg.answer("Админка.", reply_markup=_admin_menu_kb())
        return
    if state.get("step") == "target":
        if not text or text.startswith("/"):
            await msg.answer("Пришли @username или id. Или напиши «отмена».")
            return
        uid, uname = _parse_block_target(text)
        if state.get("mode") == "unblock":
            _ADMIN_WAIT.pop(user.id, None)
            if uid:
                reply = blocklist.unblock_user(user_id=uid)
            else:
                reply = blocklist.unblock_user(username=uname)
            await msg.answer(reply, reply_markup=_kb_for(msg))
            return
        _ADMIN_WAIT[user.id] = {"step": "reason", "user_id": uid, "username": uname}
        who = f"id:{uid}" if uid else uname
        await msg.answer(
            f"Кого блокируем: {who}\n\n"
            "Напиши причину. Этот текст человек увидит на любое сообщение боту.\n"
            "Отмена - напиши «отмена».",
        )
        return
    reason = text
    if not reason:
        await msg.answer("Причина пустая. Напиши текст или «отмена».")
        return
    _ADMIN_WAIT.pop(user.id, None)
    reply = blocklist.block_user(
        user_id=int(state.get("user_id") or 0),
        username=state.get("username") or "",
        reason=reason,
    )
    await msg.answer(reply, reply_markup=_kb_for(msg))


@dp.message(Command("admin"), F.chat.type == "private")
@dp.message(F.text == "🛡 Админка", F.chat.type == "private")
async def btn_admin(msg: Message):
    if not msg.from_user or not _is_privileged_user(msg.from_user.username, msg.from_user.id):
        return
    _ADMIN_WAIT.pop(msg.from_user.id, None)
    await msg.answer(
        "Админка.\nЗаблокировать человека и написать причину. "
        "Он увидит этот текст на любое сообщение.",
        reply_markup=_admin_menu_kb(),
    )


@dp.callback_query(F.data.startswith("adm:"))
async def admin_callback(cb: CallbackQuery):
    user = cb.from_user
    if not user or not _is_privileged_user(user.username, user.id):
        await cb.answer("Нет доступа.", show_alert=True)
        return
    action = (cb.data or "").split(":", 1)[1]
    if action == "list":
        await cb.answer()
        if cb.message:
            await cb.message.answer(blocklist.list_blocked())
        return
    if action == "block":
        _ADMIN_WAIT[user.id] = {"step": "target", "mode": "block"}
        await cb.answer()
        if cb.message:
            await cb.message.answer(
                "Пришли @username или числовой id.\n"
                "Дальше бот спросит причину.\n"
                "Отмена - напиши «отмена».",
            )
        return
    if action == "unblock":
        _ADMIN_WAIT[user.id] = {"step": "target", "mode": "unblock"}
        await cb.answer()
        if cb.message:
            await cb.message.answer("Кого разблокировать? Пришли @username или id.\nОтмена - «отмена».")
        return
    await cb.answer()


@dp.message(Command("block"))
async def cmd_block(msg: Message):
    if not msg.from_user or not _is_privileged_user(msg.from_user.username, msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.answer(
            "Использование: <code>/block @username причина</code> или <code>/block 123456789 причина</code>",
            parse_mode="HTML",
        )
        return
    target = parts[1].strip()
    reason = parts[2].strip() if len(parts) > 2 else ""
    if target.isdigit():
        reply = blocklist.block_user(user_id=int(target), reason=reason)
    else:
        reply = blocklist.block_user(username=target, reason=reason)
    await msg.answer(reply)


@dp.message(Command("unblock"))
async def cmd_unblock(msg: Message):
    if not msg.from_user or not _is_privileged_user(msg.from_user.username, msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Использование: <code>/unblock @username</code> или <code>/unblock 123456789</code>", parse_mode="HTML")
        return
    target = parts[1].strip()
    if target.isdigit():
        reply = blocklist.unblock_user(user_id=int(target))
    else:
        reply = blocklist.unblock_user(username=target)
    await msg.answer(reply)


@dp.message(Command("blocklist"))
async def cmd_blocklist(msg: Message):
    if not msg.from_user or not _is_privileged_user(msg.from_user.username, msg.from_user.id):
        return
    await msg.answer(blocklist.list_blocked())


@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика", F.chat.type == "private")
async def cmd_stats(msg: Message):
    uname = msg.from_user.username if msg.from_user else None
    uid = msg.from_user.id if msg.from_user else 0
    if not _is_privileged_user(uname, uid):
        return
    rep = reputation.stats()
    body = analytics.format_dashboard_html()
    await msg.answer(
        body + "\n\n"
        f"<i>База репутации:</i> операций {rep['seen_ops']}, "
        f"известных фейков {rep['known_fakes']}",
        parse_mode="HTML",
    )


@dp.message(F.successful_payment)
async def handle_stars_payment(msg: Message):
    """User paid Telegram Stars — credit one extra check."""
    uid = msg.from_user.id
    # Give 5 extra checks per payment (stars_per_check × 5 = 5 stars bundle)
    used = _checks_used(uid)
    bonus = 5
    _user_checks[uid] = (_today(), max(0, used - bonus))
    await msg.answer(
        f"⭐ Оплата получена! Добавлено <b>{bonus}</b> проверок.",
        parse_mode="HTML",
        reply_markup=_kb_for(msg),
    )


@dp.message(F.document)
async def handle_document(msg: Message):
    if msg.from_user and msg.from_user.is_bot:
        return
    doc: Document = msg.document
    uid = msg.from_user.id if msg.from_user else 0

    is_group = msg.chat.type in ("group", "supergroup")

    # Subscription gate — only enforce in private chats
    if not is_group and await _require_subscription(msg):
        return

    # Gate 1: extension check (fast, before downloading)
    fname = (doc.file_name or "").lower()
    mime  = (doc.mime_type or "").lower()
    if not fname.endswith(".pdf") and mime != "application/pdf":
        # In groups, silently ignore non-PDF files (avoid spam on every attachment).
        if not is_group:
            await msg.answer(
                "<b>Нужен PDF</b>\n"
                "<i>Скриншоты и фото не проверяются. "
                "Выгрузите чек из приложения банка в PDF.</i>",
                parse_mode="HTML",
            )
        return

    if not await _acquire_user_check_slot(uid):
        await msg.reply(
            "<b>Слишком много чеков сразу</b>\n"
            f"<i>Не больше {MAX_INFLIGHT_CHECKS_PER_USER} одновременно. "
            "Дождитесь результатов и отправьте следующие.</i>",
            parse_mode="HTML",
        )
        return

    # Ответ реплаем на сообщение с чеком
    status_msg = await msg.reply("⏳ Проверяю чек…")
    t0 = time.perf_counter()

    try:
        file = await _tg_call("get_file", lambda: bot.get_file(doc.file_id))

        async def _download():
            buf = BytesIO()
            await bot.download_file(file.file_path, buf)
            return buf.getvalue()

        pdf_bytes = await _tg_call("download_file", _download)
        t_download = time.perf_counter()

        # Gate 2: magic bytes — real PDF starts with "%PDF-"
        if not pdf_bytes.startswith(b"%PDF-"):
            await _edit_status_text(status_msg, "⚠️ Файл не является PDF (неверная сигнатура).")
            return

        bank, result, is_tbank = await asyncio.to_thread(route_bank, pdf_bytes)
        t_route = time.perf_counter()

        uname = msg.from_user.username if msg.from_user else None

        # Reputation / crowdsourced layer. The SBP-id validation is calibrated to
        # T-Bank's "00117" id format, so only apply it there; the known-fake hash
        # database is bank-agnostic and always runs.
        parsed_fields = None
        rtext = ""
        try:
            pdoc = fitz.open(stream=pdf_bytes, filetype="pdf")
            rtext = "".join(p.get_text() for p in pdoc)
            pdoc.close()
            if is_tbank:
                parsed_fields = parse_receipt(pdf_bytes)
                rep = reputation.check(pdf_bytes, parsed_fields, rtext)
            else:
                parsed_fields = parse_receipt(pdf_bytes)
                rep = reputation.check_known_fake(pdf_bytes, rtext)
        except Exception:
            logging.exception("reputation check failed")
            # Still apply static/user known-fake registry if full check crashed.
            try:
                rep = reputation.check_known_fake(pdf_bytes, rtext)
            except Exception:
                rep = {"score": 0, "flags": [], "opid": None,
                       "file_hash": reputation.file_hash(pdf_bytes)}

        result["score"] += rep["score"]
        result["flags"] += rep["flags"]
        if rep.get("custom_message"):
            result["custom_message"] = rep["custom_message"]
        # Static/user known-fake registry is decisive for non-T-Bank banks.
        if rep.get("known_fake") or int(rep.get("score") or 0) >= 95:
            details = dict(result.get("details") or {})
            details["known_fake_count"] = max(int(details.get("known_fake_count") or 0), 1)
            details["verdict_after_reputation"] = "ФЕЙК"
            result["details"] = details
            result["verdict"] = "ФЕЙК"
            result["emoji"] = "🔴"
            result["score"] = max(int(result.get("score") or 0), 95)
        else:
            details = dict(result.get("details") or {})
            details["verdict_after_reputation"] = result.get("verdict")
            result["details"] = details
        result = _normalize_binary_result(result)

        # neutral 'seen before' marker (does NOT affect the verdict)
        try:
            seen_before = reputation.record_seen(pdf_bytes)
        except Exception:
            seen_before = False

        # Who checked this receipt before (same file or same bank operation).
        # Shown under the verdict only when there is prior history.
        try:
            prior_checks = check_history.record(
                pdf_bytes, rtext, parsed_fields,
                user_id=uid, username=uname, bank=bank or "",
            )
        except Exception:
            logging.exception("check_history record failed")
            prior_checks = []

        is_fake = result.get("verdict") == "ФЕЙК" or result["score"] >= FAKE_THRESHOLD
        token = rep["file_hash"][:16]
        _report_cache_put(
            token,
            (rep["file_hash"], rep["opid"], parsed_fields, pdf_bytes, bank or "", bool(is_tbank)),
        )

        try:
            analytics.log_check(
                uid,
                username=uname,
                first_name=msg.from_user.first_name if msg.from_user else None,
                last_name=msg.from_user.last_name if msg.from_user else None,
                chat_type=msg.chat.type,
                bank=bank,
                verdict=result.get("verdict"),
                filename=doc.file_name,
                score=result.get("score", 0),
            )
        except Exception:
            logging.exception("analytics log_check failed")

        history_lines = check_history.history_lines(prior_checks)
        text = _format_result(pdf_bytes, result, bank, is_tbank, seen_before,
                              username=uname, user_id=uid, text=rtext,
                              filename=doc.file_name or "", history=history_lines)
        if _is_verbose_user(uname, uid) and history_lines:
            # Verbose (expert) layout is unchanged; append history as a plain block.
            text += "\n\n" + _html_safe(check_history.format_history(prior_checks))
        # One neutral label for both directions; the callback still carries
        # which way the report goes so the handlers stay unchanged.
        report_cb = f"genuine:{token}" if is_fake else f"fake:{token}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Сообщить об ошибке", callback_data=report_cb)
        ]])
        await _edit_status_text(status_msg, text, parse_mode="HTML", reply_markup=kb)
        t_reply = time.perf_counter()

        # Archive is secondary; do not delay the user-facing result.
        _spawn_bg(
            _archive_checked_pdf(
                msg,
                doc,
                pdf_bytes,
                bank=bank,
                result=result,
                file_hash=rep["file_hash"],
            )
        )
        logging.info(
            "check_timing uid=%s file=%s download=%.2fs route=%.2fs reply=%.2fs total=%.2fs",
            uid,
            doc.file_name,
            t_download - t0,
            t_route - t_download,
            t_reply - t_route,
            t_reply - t0,
        )

        if not is_group and campaign_is_active():
            try:
                campaign_service.process_upload(
                    user_id=uid,
                    username=uname,
                    pdf_bytes=pdf_bytes,
                    bank_name=bank or "",
                    result=result,
                )
                # Silent campaign intake — no accept/reject spam to user.
            except Exception:
                logging.exception("campaign process_upload failed")

    except TelegramNetworkError:
        logging.exception("Error analyzing PDF (telegram network)")
        try:
            await _edit_status_text(
                status_msg,
                "<b>Не удалось скачать файл</b>\n"
                "<i>Сбой связи с Telegram. Отправьте PDF ещё раз.</i>",
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("failed to edit network error status")
    except Exception as e:
        logging.exception("Error analyzing PDF")
        try:
            # Keep user-facing text short; hide raw aiohttp/transport dumps.
            brief = str(e)
            if "ServerDisconnected" in brief or "TelegramNetworkError" in brief:
                brief = "Временный сбой сети."
            elif len(brief) > 160:
                brief = brief[:157] + "..."
            await _edit_status_text(
                status_msg,
                "<b>Проверка не удалась</b>\n"
                f"<i>{_html_safe(brief)} Отправьте файл ещё раз; "
                f"если повторится - напишите в поддержку {SUPPORT_USERNAME}.</i>",
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("failed to edit error status")
    finally:
        await _release_user_check_slot(uid)


@dp.callback_query(F.data.startswith("fake:"))
async def report_fake_cb(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    entry = _report_cache.get(token)
    if not entry:
        await cb.answer("Не удалось найти этот чек (бот перезапускался). "
                        "Отправьте файл заново.", show_alert=True)
        return
    fh, opid, parsed, _pdf, _bank, _is_tbank = entry
    newly = reputation.report_fake(fh, opid, cb.from_user.id)
    # Blacklist the receiver's payout requisites — the one thing a forger cannot
    # change. After this, every receipt to the same wallet is flagged, regardless
    # of regenerated file / opid / font / ID.
    try:
        req_added = reputation.blacklist_requisites(parsed, cb.from_user.id)
    except Exception:
        logging.exception("blacklist_requisites failed")
        req_added = 0
    if newly or req_added:
        msg = "Спасибо! Чек добавлен в базу подделок - теперь он не пройдёт проверку ни у кого."
        if req_added:
            msg += " Реквизиты получателя занесены в чёрный список - любые новые чеки на этот кошелёк будут помечены как подделка."
        await cb.answer(msg, show_alert=True)
    else:
        await cb.answer("Этот чек уже был в базе подделок.", show_alert=True)


@dp.callback_query(F.data.startswith("genuine:"))
async def report_genuine_cb(cb: CallbackQuery):
    """Подтверждённый оригинал — зачислить в корпус (Т-Банк) и снять ложный фейк при повторной отправке."""
    token = cb.data.split(":", 1)[1]
    entry = _report_cache.get(token)
    if not entry:
        await cb.answer(
            "Не удалось найти этот чек (бот перезапускался). Отправьте файл заново.",
            show_alert=True,
        )
        return
    fh, opid, parsed, pdf_bytes, bank, is_tbank = entry
    enrolled = False
    # route() returns the display name («Т-Банк»), not the key — use the
    # is_tbank flag captured at check time.
    if is_tbank and pdf_bytes:
        try:
            from detector.tbank_enroll import enroll_tbank_original

            text = fitz.open(stream=pdf_bytes, filetype="pdf")[0].get_text()
            enroll_tbank_original(pdf_bytes, text)
            enrolled = True
        except Exception:
            logging.exception("tbank enroll failed")
    if enrolled:
        await cb.answer(
            "Записали как оригинал: шаблон сборки и отпечаток рендера добавлены в базу. "
            "Перешлите тот же PDF ещё раз - должен пройти.",
            show_alert=True,
        )
    else:
        await cb.answer(
            "Спасибо! Если чек настоящий, дождитесь зачисления в банке.",
            show_alert=True,
        )


@dp.pre_checkout_query()
async def pre_checkout(query):
    """Required by Telegram — must answer within 10 seconds."""
    await bot.answer_pre_checkout_query(query.id, ok=True)



# ── Profile ───────────────────────────────────────────────────────────────────

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text.in_({BTN_PROFILE, _OLD_BTN_PROFILE}), F.chat.type == "private")
async def btn_my_profile(msg: Message):
    if await _require_subscription(msg):
        return
    uid = msg.from_user.id
    uname = msg.from_user.username
    await msg.answer(
        _profile_text(uid, uname),
        parse_mode="HTML",
        reply_markup=_main_keyboard(uid, uname),
    )


@dp.message(F.text == "💰 Моя статистика", F.chat.type == "private")
async def btn_stale_stats(msg: Message):
    """Old reply-keyboard cache may still show the campaign button."""
    if await _require_subscription(msg):
        return
    uid = msg.from_user.id
    uname = msg.from_user.username
    await msg.answer(
        "Акция завершена. Клавиатура обновлена.",
        reply_markup=_main_keyboard(uid, uname),
    )


@dp.callback_query(F.data.in_({"camp:stats", "camp:rules", "camp:my_checks"}))
@dp.callback_query(F.data.startswith("camp:check:"))
async def cb_camp_gone(cb: CallbackQuery):
    await cb.answer("Акция завершена.", show_alert=True)


def _require_campaign_admin(msg: Message) -> bool:
    uname = msg.from_user.username if msg.from_user else None
    uid = msg.from_user.id if msg.from_user else 0
    return is_campaign_admin(uname, uid)


@dp.message(Command("campaign_stats"))
async def cmd_campaign_stats(msg: Message):
    if not _require_campaign_admin(msg):
        return
    s = campaign_service.campaign_stats()
    st = s.get("by_status") or {}
    banks = "\n".join(f"  {k}: {v}" for k, v in (s.get("by_bank_accepted") or [])[:20]) or "  -"
    await msg.answer(
        "<b>/campaign_stats</b>\n"
        f"Участников: {s['participants']}\n"
        f"Загружено: {s['uploaded']}\n"
        f"pending: {st.get('pending', 0)}\n"
        f"accepted: {st.get('accepted', 0)}\n"
        f"fake: {st.get('fake', 0)}\n"
        f"rejected: {st.get('rejected', 0)}\n"
        f"duplicate: {st.get('duplicate', 0)}\n"
        f"unsupported: {st.get('unsupported', 0)}\n"
        f"reversed: {st.get('reversed', 0)}\n"
        f"К выплате: {format_money_kopecks(s['payout_owed'])}\n"
        f"По банкам (accepted):\n{banks}",
        parse_mode="HTML",
    )


@dp.message(Command("campaign_user"))
async def cmd_campaign_user(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Использование: /campaign_user <user_id|username>")
        return
    view = campaign_service.user_admin_view(parts[1].strip())
    if not view:
        await msg.answer("Пользователь не найден")
        return
    hist = "\n".join(
        f"#{h['id']} {h['operation_type']} {h['amount_kopecks']} - {h['reason']}"
        for h in (view.get("ledger") or [])[:15]
    ) or "-"
    await msg.answer(
        f"<b>User {view['user_id']}</b> @{view.get('username') or '-'}\n"
        f"Загрузок: {view['uploaded']}\n"
        f"Принято: {view['accepted']}\n"
        f"Фейков: {view['fake']}\n"
        f"Дубликатов: {view['duplicate']}\n"
        f"Баланс: {format_money_kopecks(view['balance'])}\n\n"
        f"Журнал:\n{hist}",
        parse_mode="HTML",
    )


@dp.message(Command("accept_check"))
async def cmd_accept_check(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.answer("Использование: /accept_check <check_id>")
        return
    out = campaign_service.accept_check(
        int(parts[1]), msg.from_user.id, msg.from_user.username,
    )
    if not out.get("ok"):
        await msg.answer(f"Ошибка: {out.get('error')}")
        return
    uid = out.get("user_id")
    reward = format_money_kopecks(int(out.get("reward_kopecks") or 0))
    bal_txt = "-"
    if uid is not None:
        view = campaign_service.user_admin_view(str(uid))
        if view:
            bal_txt = format_money_kopecks(int(view.get("balance") or 0))
    await msg.answer(
        f"OK accepted #{out.get('check_id')} "
        f"status={out.get('status', 'accepted')} "
        f"reward={reward} user={uid} balance={bal_txt}"
    )


@dp.message(Command("campaign_balances"))
async def cmd_campaign_balances(msg: Message):
    if not _require_campaign_admin(msg):
        return
    rows = campaign_service.campaign_balances()[:40]
    lines = ["user_id | username | принято | баланс"]
    for r in rows:
        lines.append(
            f"{r['user_id']} | @{r.get('username') or '-'} | "
            f"{r.get('accepted', 0)} | {format_money_kopecks(int(r.get('balance') or 0))}"
        )
    text_out = "\n".join(lines)
    if len(text_out) > 3900:
        text_out = text_out[:3900] + "\n…"
    await msg.answer(f"<pre>{html.escape(text_out)}</pre>", parse_mode="HTML")


@dp.message(Command("campaign_export"))
async def cmd_campaign_export(msg: Message):
    if not _require_campaign_admin(msg):
        return
    csv_data = campaign_service.export_csv()
    await msg.answer_document(
        BufferedInputFile(csv_data.encode("utf-8-sig"), filename="campaign_export.csv"),
        caption="campaign export",
    )


@dp.message(Command("payout_mark"))
async def cmd_payout_mark(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await msg.answer("Использование: /payout_mark <user_id> paid|rejected [reason]")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.answer("user_id должен быть числом")
        return
    status = parts[2].lower()
    reason = parts[3] if len(parts) > 3 else ""
    out = campaign_service.payout_mark(
        uid, status, msg.from_user.id, reason, msg.from_user.username,
    )
    if not out.get("ok"):
        await msg.answer(f"Ошибка: {out.get('error')}")
        return
    if status == "paid":
        await msg.answer(
            f"Выплачено\nСумма: {format_money_kopecks(out.get('amount') or 0)}\n"
            f"Администратор: @{msg.from_user.username}"
        )
    else:
        await msg.answer(f"OK payout {status} user={uid}")



@dp.message(F.chat.type == "private")
async def fallback(msg: Message):
    if await _require_subscription(msg):
        return
    await msg.answer(
        "<b>Пришлите PDF-чек</b>\n<i>Текст и картинки я не проверяю</i>",
        parse_mode="HTML",
        reply_markup=_kb_for(msg),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

# Same items as the reply keyboard (Menu button next to the input field).
_PUBLIC_BOT_COMMANDS = [
    BotCommand(command="check", description=BTN_CHECK),
    BotCommand(command="banks", description=BTN_BANKS),
    BotCommand(command="mail", description=BTN_MAIL),
    BotCommand(command="support", description=BTN_SUPPORT),
    BotCommand(command="profile", description=BTN_PROFILE),
]

_ADMIN_BOT_COMMANDS = _PUBLIC_BOT_COMMANDS + [
    BotCommand(command="stats", description="📊 Статистика"),
    BotCommand(command="admin", description="🛡 Админка"),
]


# "What can this bot do?" block under the cover in an empty chat (≤512 chars)
# and the one-liner in the profile / share card (≤120 chars). Set on every
# start so a foreign description (e.g. the PDF Forge generator text that once
# ran on this token) never sticks.
BOT_DESCRIPTION = (
    "PROTON. Проверка банковских чеков на подлинность\n"
    "\n"
    "📄 Пришлите PDF из приложения банка\n"
    "✅ Ответ за секунды: оригинал или подделка\n"
    "🏦 19 банков: Т-Банк, Сбер, Альфа, ВТБ, Озон и другие\n"
    "✉️ Проверка писем от банка по подписи сервера\n"
    "\n"
    "Бесплатно. Результаты носят информационный характер.\n"
    f"Поддержка: {SUPPORT_USERNAME}"
)
BOT_SHORT_DESCRIPTION = "Проверка банковских PDF-чеков на подлинность"


async def _setup_bot_description() -> None:
    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    except Exception:
        logging.exception("set_my_description failed")


async def _setup_bot_menu() -> None:
    """Blue Menu button = same actions as the bottom keyboard."""
    await _setup_bot_description()
    await bot.set_my_commands(_PUBLIC_BOT_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                _ADMIN_BOT_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logging.exception("set_my_commands failed for admin_id=%s", admin_id)


async def main():
    logging.info("Bot started")
    await _setup_bot_menu()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
