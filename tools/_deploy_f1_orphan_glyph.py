"""Deploy T-Bank F1 orphan simple glyph HARD (v6.4.0) to Aeza."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/tbank_f1_orphan_glyph.py",
    "detector/tbank_v6/stages.py",
    "detector/tbank_v6/rules.py",
    "detector/tbank_v6/explain.py",
    "detector/tbank_v6/engine.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=120):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector/tbank_v6")
for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/tbank_f1_orphan_glyph.py "
    "detector/tbank_v6/stages.py "
    "detector/tbank_v6/rules.py "
    "detector/tbank_v6/explain.py "
    "detector/tbank_v6/engine.py"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print(run("systemctl is-active pdfbot pdfmail").strip())

fake = Path(
    r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\чеки_30_из_30\sbp30_01.pdf"
).read_bytes()
with sftp.file("/tmp/sbp30_01.pdf", "wb") as f:
    f.write(fake)

print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.tbank import analyze, VALIDATOR_VERSION; "
    "r=analyze(Path('/tmp/sbp30_01.pdf').read_bytes()); "
    "print(VALIDATOR_VERSION); print(r['verdict'], r['score']); "
    "print([x for x in r.get('flags') or [] if 'ORPHAN' in x])\""
))
sftp.close()
ssh.close()
print("DEPLOYED")
