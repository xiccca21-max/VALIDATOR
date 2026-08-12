# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\bot.py")
t = p.read_text(encoding="utf-8")

# Remove any remaining campaign user notifications
t2, n = re.subn(
    r"\n[ \t]*await _campaign_notify_user\([\s\S]*?\n[ \t]*\)\n",
    "\n",
    t,
)
print("removed notify calls", n)
p.write_text(t2, encoding="utf-8")
print("left", t2.count("await _campaign_notify_user"))
