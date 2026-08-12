"""Deploy T-Bank SBP slot/suffix linked-tuple catch (receipt_30.07.2026.pdf)."""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/tbank_sbp_content.py",
    "detector/reputation.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

fake_local = Path(r"c:\Users\fanis\Downloads\Telegram Desktop\receipt_30.07.2026.pdf")
sftp.put(str(fake_local), f"{cfg.BOT_DIR}/_smoke_tbank_slot014.pdf")
print("uploaded smoke pdf")

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/tbank_sbp_content.py detector/reputation.py"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

smoke_py = r"""
from pathlib import Path
from detector import route as route_bank
pdf = Path('_smoke_tbank_slot014.pdf').read_bytes()
bank, res, _ = route_bank(pdf)
print(bank, res.get('verdict'), res.get('score'))
for f in res.get('flags') or []:
    print(f)
"""
sftp.putfo(io.BytesIO(smoke_py.encode()), f"{cfg.BOT_DIR}/_smoke_tbank_slot014_check.py")
print("SMOKE:\n", run(f"cd {cfg.BOT_DIR} && venv/bin/python _smoke_tbank_slot014_check.py"))
sftp.close()
ssh.close()
