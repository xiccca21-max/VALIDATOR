#!/usr/bin/env python3
"""Deploy recipient-bank extraction fix."""

from __future__ import annotations

import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "bot.py",
    "detector/__init__.py",
    "detector/parser.py",
    "detector/recipient_bank.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


print(f"Connecting to {cfg.HOST} ...")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile " + " ".join(FILES)))
print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(
    run(
        f"cd {cfg.BOT_DIR} && python3 - <<'PY'\n"
        "from detector.recipient_bank import extract_recipient_bank_fields\n"
        "print('ok', callable(extract_recipient_bank_fields))\n"
        "PY"
    )
)
sftp.close()
ssh.close()
print("Done — recipient bank fix deployed")
