# -*- coding: utf-8 -*-
from pathlib import Path

root = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")

# --- texts.py ---
texts = root / "campaign" / "texts.py"
t = texts.read_text(encoding="utf-8")

old_profile = '''def profile_text(user_id: int, username: str | None, snap: dict) -> str:
    uname = f"@{username}" if username else "—"
    return (
        f"👤 <b>Мой профиль</b>\\n\\n"
        f"ID: <code>{user_id}</code>\\n"
        f"Username: {uname}\\n\\n"
        f"Загружено чеков: <b>{snap['uploaded']}</b>\\n"
        f"На проверке: <b>{snap['pending']}</b>\\n"
        f"Принято: <b>{snap['accepted']}</b>\\n"
        f"Отклонено: <b>{snap['rejected']}</b>\\n"
        f"Дубликаты: <b>{snap['duplicate']}</b>\\n"
        f"Фейки: <b>{snap['fake']}</b>\\n\\n"
        f"Баланс к выплате: <b>{snap['balance_text']}</b>\\n"
        f"Выплаты: после окончания акции"
    )'''

new_profile = '''def profile_text(user_id: int, username: str | None, snap: dict) -> str:
    uname = f"@{username}" if username else "—"
    return (
        f"👤 <b>Мой профиль</b>\\n\\n"
        f"ID: <code>{user_id}</code>\\n"
        f"Username: {uname}\\n\\n"
        f"<b>Акция:</b> 1 принятый оригинал = 10 ₽\\n"
        f"Ниже — только статистика по этой акции.\\n\\n"
        f"Загружено чеков: <b>{snap['uploaded']}</b>\\n"
        f"Принято: <b>{snap['accepted']}</b>\\n"
        f"Отклонено: <b>{snap['rejected']}</b>\\n\\n"
        f"Баланс к выплате: <b>{snap['balance_text']}</b>\\n"
        f"Выплаты: после окончания акции"
    )'''

# Use actual newlines in file
old_profile = old_profile.replace("\\n", "\n")
new_profile = new_profile.replace("\\n", "\n")

if old_profile not in t:
    raise SystemExit("profile_text block not found")
t = t.replace(old_profile, new_profile, 1)

old_stats = '''def stats_text(snap: dict) -> str:
    return (
        f"💰 <b>Моя статистика</b>\\n\\n"
        f"Загружено: <b>{snap['uploaded']}</b>\\n"
        f"На проверке: <b>{snap['pending']}</b>\\n"
        f"Принято: <b>{snap['accepted']}</b>\\n"
        f"Отклонено: <b>{snap['rejected'] + snap.get('unsupported', 0)}</b>\\n"
        f"Дубликаты: <b>{snap['duplicate']}</b>\\n\\n"
        f"К выплате после окончания акции: <b>{snap['balance_text']}</b>"
    )'''
old_stats = old_stats.replace("\\n", "\n")
new_stats = '''def stats_text(snap: dict) -> str:
    return (
        f"💰 <b>Статистика акции</b>\\n\\n"
        f"Акция: 1 принятый оригинал = 10 ₽\\n\\n"
        f"Загружено: <b>{snap['uploaded']}</b>\\n"
        f"Принято: <b>{snap['accepted']}</b>\\n"
        f"Отклонено: <b>{snap['rejected'] + snap.get('unsupported', 0)}</b>\\n\\n"
        f"К выплате после окончания акции: <b>{snap['balance_text']}</b>"
    )'''.replace("\\n", "\n")
if old_stats in t:
    t = t.replace(old_stats, new_stats, 1)
    print("stats_text updated")
else:
    print("WARN stats_text not found")

texts.write_text(t, encoding="utf-8")
print("texts ok")

# --- bot.py inline kb: remove Статистика button ---
bot = root / "bot.py"
b = bot.read_text(encoding="utf-8")
old_kb = '''def _profile_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📄 Мои чеки", callback_data="camp:my_checks"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="camp:stats"),
        ],
        [InlineKeyboardButton(text="📋 Правила акции", callback_data="camp:rules")],
    ])
'''
new_kb = '''def _profile_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Мои чеки", callback_data="camp:my_checks")],
        [InlineKeyboardButton(text="📋 Правила акции", callback_data="camp:rules")],
    ])
'''
if old_kb not in b:
    raise SystemExit("profile inline kb not found")
b = b.replace(old_kb, new_kb, 1)
bot.write_text(b, encoding="utf-8")
print("inline kb ok, stats button gone", "camp:stats" in b and "📊 Статистика" not in b)
