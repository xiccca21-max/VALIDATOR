"""Deploy SFNT inventory + linked-tuple atlas update."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/tbank_sfnt_table_integrity.py",
    "detector/tbank_sbp_content.py",
    "detector/tbank_v6/rules.py",
    "detector/tbank_v6/stages.py",
    "detector/tbank_v6/explain.py",
    "detector/tbank_v6/engine.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 180) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for rel in FILES:
    local = HERE / rel.replace("/", os.sep)
    sftp.put(str(local), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile " + " ".join(FILES)))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

smoke = Path(
    r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\_v3_test15"
    r"\receipt_21.07.2026_test_9.pdf"
)
with sftp.file("/tmp/tbank_sfnt_smoke.pdf", "wb") as f:
    f.write(smoke.read_bytes())
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.tbank import analyze, VALIDATOR_VERSION; "
    "r=analyze(Path('/tmp/tbank_sfnt_smoke.pdf').read_bytes()); "
    "cs=[x[1:x.index(']')] for x in (r.get('flags') or []) if x.startswith('[')]; "
    "print('version', VALIDATOR_VERSION); "
    "print('verdict', r.get('verdict')); "
    "print('zzzz', 'TBANK_TTF_INERT_PADDING_TABLE' in cs); "
    "print('linked', 'SBP_LINKED_TUPLE_CONFLICT' in cs); "
    "print([c for c in cs if 'TTF' in c or 'LINKED' in c or 'INERT' in c])\""
))

sftp.close()
ssh.close()
print("DEPLOYED")
