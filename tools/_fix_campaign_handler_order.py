# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\bot.py")
t = path.read_text(encoding="utf-8")

marker = "\n# ── Campaign user UI"
start = t.find(marker)
if start < 0:
    raise SystemExit("campaign UI marker not found")
end = t.find("\nasync def main():")
if end < 0:
    raise SystemExit("main() not found")

block = t[start:end]
t2 = t[:start] + t[end:]

fb = t2.find('@dp.message(F.chat.type == "private")\nasync def fallback')
if fb < 0:
    raise SystemExit("fallback not found")

t3 = t2[:fb] + block + "\n\n" + t2[fb:]
path.write_text(t3, encoding="utf-8")

t = path.read_text(encoding="utf-8")
p = t.find("async def btn_my_profile")
f = t.find("async def fallback")
print("profile_pos", p)
print("fallback_pos", f)
print("order_ok", p >= 0 and f >= 0 and p < f)
print("size", len(t))
