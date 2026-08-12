import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/ozon_sbp_tail.py",
    "detector/ozon.py",
    "detector/ozon_v1/engine.py",
    "detector/ozon_v1/stages.py",
    "detector/ozon_v1/rules.py",
    "detector/ozon_v1/verdict.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=90):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector/ozon_v1")
for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/ozon_sbp_tail.py detector/ozon.py "
    "detector/ozon_v1/engine.py detector/ozon_v1/stages.py "
    "detector/ozon_v1/rules.py detector/ozon_v1/verdict.py"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print(run("systemctl is-active pdfbot pdfmail").strip())

pdf = Path(
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260721190357.pdf"
).read_bytes()
with sftp.file("/tmp/ozon_fp.pdf", "wb") as f:
    f.write(pdf)

print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.ozon_v1.engine import analyze; "
    "r=analyze(Path('/tmp/ozon_fp.pdf').read_bytes(), "
    "source_filename='ozonbank_document_20260721190357.pdf'); "
    "print(r['verdict']); print(r.get('flags'))\""
))
sftp.close()
ssh.close()
print("DEPLOYED")
