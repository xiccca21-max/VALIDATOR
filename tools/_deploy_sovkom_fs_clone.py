"""Deploy Sovkom Flying Saucer clone-kit catch (producer pin + SBP cipher)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/bank_specs/sovkom.json",
    "detector/bank_spec_engine.py",
    "detector/policy_v5.py",
    "detector/verdict.py",
    "detector/sparse9_v1/stages.py",
    "detector/sparse9_v1/rules.py",
    "detector/reputation.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector/bank_specs {cfg.BOT_DIR}/detector/sparse9_v1")
for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

fake_local = Path(
    r"c:\Users\fanis\Downloads\Telegram Desktop\cf0e2089-7c1f-4fe5-84e5-108c707146d1.pdf"
)
remote_fake = f"{cfg.BOT_DIR}/_smoke_sovkom_fake.pdf"
sftp.put(str(fake_local), remote_fake)
print("uploaded smoke pdf")

print(
    run(
        f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
        "detector/bank_spec_engine.py detector/policy_v5.py detector/verdict.py "
        "detector/sparse9_v1/stages.py detector/sparse9_v1/rules.py detector/reputation.py"
    )
)
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

smoke_py = r"""
from pathlib import Path
from detector import route as route_bank
pdf = Path('_smoke_sovkom_fake.pdf').read_bytes()
bank, res, _ = route_bank(pdf)
print(bank, res.get('verdict'), res.get('score'))
for f in res.get('flags') or []:
    print(f)
"""
sftp.putfo(
    __import__("io").BytesIO(smoke_py.encode()),
    f"{cfg.BOT_DIR}/_smoke_sovkom_check.py",
)
print("SMOKE:\n", run(f"cd {cfg.BOT_DIR} && venv/bin/python _smoke_sovkom_check.py"))
sftp.close()
ssh.close()
