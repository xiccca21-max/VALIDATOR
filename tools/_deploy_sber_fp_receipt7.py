"""Deploy Sber cross-doc + geometry false-positive fixes."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/sber_v2/cross_document.py",
    "detector/sber_v2/geometry.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for rel in FILES:
    sftp.put(str(HERE / rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    + " ".join(FILES)
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

smoke = Path(
    r"C:\Users\fanis\OneDrive\Desktop\чеки\сбер_оригиналы_v2\Новая папка (2)\receipt (7).pdf"
)
with sftp.file("/tmp/sber_receipt7.pdf", "wb") as f:
    f.write(smoke.read_bytes())
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.sber import analyze; "
    "r=analyze(Path('/tmp/sber_receipt7.pdf').read_bytes()); "
    "print('verdict=', r.get('verdict')); "
    "print('flags=', r.get('flags'))\""
))

sftp.close()
ssh.close()
print("DEPLOYED")
