# -*- coding: utf-8 -*-
import re
from pathlib import Path

p = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\bot.py")
t = p.read_text(encoding="utf-8")

t = t.replace(
    '[KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="💰 Моя статистика")]',
    '[KeyboardButton(text="👤 Мой профиль")]',
)

old = "                await _campaign_notify_user(uid, camp)\n"
if old not in t:
    raise SystemExit("notify call not found")
t = t.replace(
    old,
    "                # Silent campaign intake — no accept/reject spam to user.\n",
    1,
)

# Remove reply-keyboard stats handler; keep inline camp:stats from profile
pat = re.compile(
    r'@dp\.message\(F\.text == "💰 Моя статистика".*?\n'
    r'async def btn_my_stats\(msg: Message\):\n'
    r'(?:    .*\n)+?\n',
    re.M,
)
t2, n = pat.subn("", t, count=1)
if n != 1:
    print("WARN: btn_my_stats not removed", n)
else:
    t = t2
    print("removed btn_my_stats")

p.write_text(t, encoding="utf-8")
print("stats in keyboard", t.count('💰 Моя статистика'))
print("notify left", "_campaign_notify_user(uid, camp)" in t)
print("profile btn", t.count('👤 Мой профиль'))
