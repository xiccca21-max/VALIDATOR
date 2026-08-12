# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\bot.py")
text = path.read_text(encoding="utf-8")
if "from campaign import service" in text:
    print("already patched")
    raise SystemExit(0)

needle = "import blocklist\n"
insert_imports = """import blocklist
from campaign.config import (
    STATUS_ACCEPTED,
    STATUS_DUPLICATE,
    STATUS_FAKE,
    STATUS_REJECTED,
    STATUS_REVERSED,
    STATUS_UNSUPPORTED,
    campaign_is_active,
    format_money_kopecks,
    is_campaign_admin,
)
from campaign import service as campaign_service
from campaign import texts as campaign_texts
"""
if needle not in text:
    raise SystemExit("blocklist import not found")
text = text.replace(needle, insert_imports, 1)

old_kb = '''MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Проверить чек"), KeyboardButton(text="🏦 Проверяемые банки")],
        [KeyboardButton(text="📧 Почта"), KeyboardButton(text="💬 Поддержка")],
    ],
    resize_keyboard=True,
)


def _main_keyboard(user_id: int = 0, username: str | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="✅ Проверить чек"), KeyboardButton(text="🏦 Проверяемые банки")],
        [KeyboardButton(text="📧 Почта"), KeyboardButton(text="💬 Поддержка")],
    ]
    if _is_privileged_user(username, user_id):
        rows.append([KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
'''

new_kb = '''MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Проверить чек"), KeyboardButton(text="🏦 Проверяемые банки")],
        [KeyboardButton(text="📧 Почта"), KeyboardButton(text="💬 Поддержка")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💰 Моя статистика")],
    ],
    resize_keyboard=True,
)


def _main_keyboard(user_id: int = 0, username: str | None = None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="✅ Проверить чек"), KeyboardButton(text="🏦 Проверяемые банки")],
        [KeyboardButton(text="📧 Почта"), KeyboardButton(text="💬 Поддержка")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💰 Моя статистика")],
    ]
    if _is_privileged_user(username, user_id):
        rows.append([KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _profile_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📄 Мои чеки", callback_data="camp:my_checks"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="camp:stats"),
        ],
        [InlineKeyboardButton(text="📋 Правила акции", callback_data="camp:rules")],
    ])


def _checks_inline_kb(rows: list) -> InlineKeyboardMarkup | None:
    buttons = [[InlineKeyboardButton(text=f"#{r['id']}", callback_data=f"camp:check:{r['id']}")]
               for r in rows[:12]]
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


async def _campaign_notify_user(user_id: int, camp: dict) -> None:
    if not camp or camp.get("skipped") or not camp.get("notify"):
        return
    try:
        status = camp.get("status")
        if status == STATUS_ACCEPTED:
            snap = campaign_service.profile_snapshot(user_id)
            await bot.send_message(user_id, campaign_texts.notify_accepted(snap), parse_mode="HTML")
        elif status in (STATUS_REJECTED, STATUS_DUPLICATE, STATUS_FAKE, STATUS_UNSUPPORTED):
            reason = camp.get("reason_text") or "не соответствует условиям акции"
            await bot.send_message(user_id, campaign_texts.notify_rejected(reason), parse_mode="HTML")
        elif status == STATUS_REVERSED:
            await bot.send_message(
                user_id,
                campaign_texts.notify_reversed(camp.get("reason_text") or ""),
                parse_mode="HTML",
            )
    except Exception:
        logging.exception("campaign notify failed user_id=%s", user_id)
'''

if old_kb not in text:
    raise SystemExit("keyboard block not found")
text = text.replace(old_kb, new_kb, 1)

anchor = '''        await _edit_status_text(status_msg, text, parse_mode="HTML", reply_markup=kb)

    except Exception as e:
        logging.exception("Error analyzing PDF")
        await status_msg.edit_text(f"❌ Ошибка при анализе: {e}")
'''
inject = '''        await _edit_status_text(status_msg, text, parse_mode="HTML", reply_markup=kb)

        if not is_group and campaign_is_active():
            try:
                camp = campaign_service.process_upload(
                    user_id=uid,
                    username=uname,
                    pdf_bytes=pdf_bytes,
                    bank_name=bank or "",
                    result=result,
                )
                await _campaign_notify_user(uid, camp)
            except Exception:
                logging.exception("campaign process_upload failed")

    except Exception as e:
        logging.exception("Error analyzing PDF")
        await status_msg.edit_text(f"❌ Ошибка при анализе: {e}")
'''
if anchor not in text:
    raise SystemExit("handle_document anchor not found")
text = text.replace(anchor, inject, 1)

handlers = r'''

# ── Campaign user UI ──────────────────────────────────────────────────────────

@dp.message(F.text == "👤 Мой профиль", F.chat.type == "private")
async def btn_my_profile(msg: Message):
    if await _require_subscription(msg):
        return
    uid = msg.from_user.id
    uname = msg.from_user.username
    snap = campaign_service.profile_snapshot(uid)
    await msg.answer(
        campaign_texts.profile_text(uid, uname, snap),
        parse_mode="HTML",
        reply_markup=_profile_inline_kb(),
    )


@dp.message(F.text == "💰 Моя статистика", F.chat.type == "private")
async def btn_my_stats(msg: Message):
    if await _require_subscription(msg):
        return
    snap = campaign_service.profile_snapshot(msg.from_user.id)
    await msg.answer(campaign_texts.stats_text(snap), parse_mode="HTML")


@dp.callback_query(F.data == "camp:stats")
async def cb_camp_stats(cb: CallbackQuery):
    snap = campaign_service.profile_snapshot(cb.from_user.id)
    await cb.message.answer(campaign_texts.stats_text(snap), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "camp:rules")
async def cb_camp_rules(cb: CallbackQuery):
    await cb.message.answer(campaign_texts.rules_text(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "camp:my_checks")
async def cb_camp_my_checks(cb: CallbackQuery):
    rows = campaign_service.recent_checks(cb.from_user.id, 15)
    kb = _checks_inline_kb(rows)
    await cb.message.answer(
        campaign_texts.checks_list_text(rows),
        parse_mode="HTML",
        reply_markup=kb,
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("camp:check:"))
async def cb_camp_check_detail(cb: CallbackQuery):
    try:
        check_id = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректный id", show_alert=True)
        return
    row = campaign_service.get_check(check_id)
    if not row or int(row.get("user_id") or 0) != cb.from_user.id:
        await cb.answer("Чек не найден", show_alert=True)
        return
    await cb.message.answer(campaign_texts.check_detail_text(row), parse_mode="HTML")
    await cb.answer()


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
    banks = "\n".join(f"  {k}: {v}" for k, v in (s.get("by_bank_accepted") or [])[:20]) or "  —"
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
        f"#{h['id']} {h['operation_type']} {h['amount_kopecks']} — {h['reason']}"
        for h in (view.get("ledger") or [])[:15]
    ) or "—"
    await msg.answer(
        f"<b>User {view['user_id']}</b> @{view.get('username') or '—'}\n"
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
    await msg.answer(f"OK accepted #{out['check_id']}")
    await _campaign_notify_user(out["user_id"], {
        "status": STATUS_ACCEPTED, "notify": True, "skipped": False,
    })


@dp.message(Command("reject_check"))
async def cmd_reject_check(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await msg.answer("Использование: /reject_check <check_id> <reason>")
        return
    out = campaign_service.reject_check(
        int(parts[1]), msg.from_user.id, parts[2], msg.from_user.username,
    )
    if not out.get("ok"):
        await msg.answer(f"Ошибка: {out.get('error')}")
        return
    await msg.answer(f"OK {out['status']} #{out['check_id']}")
    await _campaign_notify_user(out["user_id"], {
        "status": out["status"],
        "reason_text": out.get("reason_text"),
        "notify": True,
        "skipped": False,
    })


@dp.message(Command("fake_check"))
async def cmd_fake_check(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await msg.answer("Использование: /fake_check <check_id> <reason>")
        return
    out = campaign_service.fake_check(
        int(parts[1]), msg.from_user.id, parts[2], msg.from_user.username,
    )
    if not out.get("ok"):
        await msg.answer(f"Ошибка: {out.get('error')}")
        return
    await msg.answer(f"OK {out['status']} #{out['check_id']}")
    await _campaign_notify_user(out["user_id"], {
        "status": out["status"],
        "reason_text": out.get("reason_text"),
        "notify": True,
        "skipped": False,
    })


@dp.message(Command("adjust_balance"))
async def cmd_adjust_balance(msg: Message):
    if not _require_campaign_admin(msg):
        return
    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await msg.answer("Использование: /adjust_balance <user_id> <amount_rub> <reason>")
        return
    try:
        uid = int(parts[1])
        rub = float(parts[2].replace(",", "."))
    except ValueError:
        await msg.answer("user_id и amount должны быть числами")
        return
    kopecks = int(round(rub * 100))
    out = campaign_service.adjust_balance(
        uid, kopecks, parts[3], msg.from_user.id, msg.from_user.username,
    )
    if not out.get("ok"):
        await msg.answer(f"Ошибка: {out.get('error')}")
        return
    await msg.answer(f"OK balance={format_money_kopecks(out['balance'])} user={uid}")


@dp.message(Command("campaign_balances"))
async def cmd_campaign_balances(msg: Message):
    if not _require_campaign_admin(msg):
        return
    rows = campaign_service.campaign_balances()[:40]
    lines = ["user_id | username | принято | баланс"]
    for r in rows:
        lines.append(
            f"{r['user_id']} | @{r.get('username') or '—'} | "
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

'''

marker = "\nasync def main():"
if marker not in text:
    raise SystemExit("main() not found")
if "btn_my_profile" not in text:
    text = text.replace(marker, handlers + marker, 1)

path.write_text(text, encoding="utf-8")
print("patched ok, size", path.stat().st_size)
print("markers", "process_upload" in text, "btn_my_profile" in text, "campaign_stats" in text)
