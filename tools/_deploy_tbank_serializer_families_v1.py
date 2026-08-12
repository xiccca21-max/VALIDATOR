"""Deploy T-Bank serializer families v1 to Aeza."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")

FILES = [
    "detector/tbank_serializer_families_v1.py",
    "detector/tbank_v6/rules.py",
    "detector/tbank_v6/stages.py",
    "detector/tbank_v6/explain.py",
    "detector/tbank_v6/engine.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for rel in FILES:
    local = HERE / rel.replace("/", os.sep)
    remote = f"{cfg.BOT_DIR}/{rel}"
    remote_dir = os.path.dirname(remote)
    run(f"mkdir -p {remote_dir}")
    sftp.put(str(local), remote)
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    + " ".join(FILES)
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot").strip())
print("pdfmail:", run("systemctl is-active pdfmail").strip())
print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -c "
    "\"from detector.tbank_v6.engine import VALIDATOR_VERSION; "
    "from detector.tbank_serializer_families_v1 import CODE_SBP, CODE_CARD_OTHER; "
    "print(VALIDATOR_VERSION, CODE_SBP, CODE_CARD_OTHER)\""
))

sftp.close()
ssh.close()
print("Done")
