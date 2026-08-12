"""Deploy Raif CID-0 content HARD fix to Aeza."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/raif_content_cid0.py",
    "detector/bank_spec_engine.py",
    "detector/policy_v5.py",
    "detector/verdict.py",
    "detector/sparse9_v1/stages.py",
    "detector/sparse9_v1/rules.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=120):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector/sparse9_v1")
for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/raif_content_cid0.py "
    "detector/bank_spec_engine.py "
    "detector/policy_v5.py "
    "detector/verdict.py "
    "detector/sparse9_v1/stages.py "
    "detector/sparse9_v1/rules.py"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print(run("systemctl is-active pdfbot pdfmail").strip())

fake = Path(r"c:\Users\fanis\Downloads\Квитанция (4).pdf").read_bytes()
with sftp.file("/tmp/raif_cid0_fake.pdf", "wb") as f:
    f.write(fake)

print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector import route as route_bank; "
    "n,r,_=route_bank(Path('/tmp/raif_cid0_fake.pdf').read_bytes()); "
    "print(n, r.get('verdict'), r.get('score')); "
    "print([x for x in (r.get('flags') or []) if 'CID_ZERO' in x or 'RAIF' in x])\""
))
sftp.close()
ssh.close()
print("DEPLOYED")
