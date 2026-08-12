"""Deploy embedded_font_reassembly_forensics to Aeza."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/embedded_font_reassembly.py",
    "detector/alfa_v2/rules.py",
    "detector/alfa_v2/stages.py",
    "detector/alfa_v2/explain.py",
    "detector/sber_v2/rules.py",
    "detector/sber_v2/stages.py",
    "detector/sber_v2/explain.py",
    "detector/tbank_v6/rules.py",
    "detector/tbank_v6/stages.py",
    "detector/tbank_v6/explain.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector")
for rel in FILES:
    local = HERE / rel.replace("/", os.sep)
    if not local.is_file():
        raise SystemExit(f"missing {rel}")
    sftp.put(str(local), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    + " ".join(FILES)
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

# remote smoke: alfa fake + one original-ish path if uploaded
smoke = Path(r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие\alfa_sbp_013424.pdf")
if smoke.is_file():
    with sftp.file("/tmp/alfa_rebuild_smoke.pdf", "wb") as f:
        f.write(smoke.read_bytes())
    print(run(
        "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
        "\"from pathlib import Path; from detector.alfa import analyze; "
        "r=analyze(Path('/tmp/alfa_rebuild_smoke.pdf').read_bytes()); "
        "rb=[x for x in (r.get('flags') or []) if 'REBUILD' in x]; "
        "print('verdict=', r.get('verdict')); print('rebuild_n=', len(rb)); "
        "print(rb[0] if rb else '')\""
    ))

sftp.close()
ssh.close()
print("DEPLOYED")
