import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
FILES = [
    "detector/alfa_v2/fonts.py",
    "detector/alfa_v2/rules.py",
    "detector/alfa_v2/atlas_data/glyph_atlas.json",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=120):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


run(f"mkdir -p {cfg.BOT_DIR}/detector/alfa_v2/atlas_data")
for rel in FILES:
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/alfa_v2/fonts.py detector/alfa_v2/rules.py"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print(run("systemctl is-active pdfbot pdfmail").strip())

fake = Path(
    r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие\alfa_sbp_013424.pdf"
).read_bytes()
with sftp.file("/tmp/alfa_fn.pdf", "wb") as f:
    f.write(fake)
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.alfa import analyze; "
    "r=analyze(Path('/tmp/alfa_fn.pdf').read_bytes()); "
    "print(r['verdict']); print(r.get('flags')[:3])\""
))
sftp.close()
ssh.close()
print("DEPLOYED")
