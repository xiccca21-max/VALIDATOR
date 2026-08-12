# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\bot.py")
t = p.read_text(encoding="utf-8")

# 1) On /start always push fresh keyboard (already does _main_keyboard) — ensure
# 2) If user taps stale "Моя статистика", show profile + refresh keyboard
needle = '@dp.callback_query(F.data == "camp:stats")'
inject = '''@dp.message(F.text == "💰 Моя статистика", F.chat.type == "private")
async def btn_stale_stats(msg: Message):
    """Old reply-keyboard cache may still show this button — refresh menu."""
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
    await msg.answer(
        "Клавиатура обновлена.",
        reply_markup=_main_keyboard(uid, uname),
    )


''' + needle

if '@dp.message(F.text == "💰 Моя статистика"' in t and 'btn_stale_stats' not in t:
    # already has some handler — replace differently
    pass

if 'btn_stale_stats' not in t:
    if needle not in t:
        raise SystemExit('camp:stats callback not found')
    t = t.replace(needle, inject, 1)
    print('added stale stats handler')
else:
    print('stale handler already present')

# Force keyboard refresh on profile button too
old_profile = '''@dp.message(F.text == "👤 Мой профиль", F.chat.type == "private")
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
'''

new_profile = '''@dp.message(F.text == "👤 Мой профиль", F.chat.type == "private")
async def btn_my_profile(msg: Message):
    if await _require_subscription(msg):
        return
    uid = msg.from_user.id
    uname = msg.from_user.username
    snap = campaign_service.profile_snapshot(uid)
    await msg.answer(
        campaign_texts.profile_text(uid, uname, snap),
        parse_mode="HTML",
        reply_markup=_main_keyboard(uid, uname),
    )
    await msg.answer(
        "Действия:",
        reply_markup=_profile_inline_kb(),
    )
'''

if old_profile in t:
    t = t.replace(old_profile, new_profile, 1)
    print('profile refreshes keyboard')
else:
    print('WARN profile block not exact')

p.write_text(t, encoding="utf-8")
print('done')
