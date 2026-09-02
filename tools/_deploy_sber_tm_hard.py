"""Deploy Sber Jasper Tm HARD rules to the live bot."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/sber_v2/content.py",
    "detector/sber_v2/rules.py",
    "detector/sber_v2/explain.py",
]
SMOKE = Path(r"C:\Users\fanis\OneDrive\Desktop\протон  проход\сбер сбп\sber_sbp_12.pdf")

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for rel in FILES:
    local = HERE / rel
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

if SMOKE.is_file():
    with sftp.file("/tmp/sber_tm_smoke.pdf", "wb") as f:
        f.write(SMOKE.read_bytes())
    print(run(
        "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
        "\"from pathlib import Path; from detector.sber import analyze; "
        "r=analyze(Path('/tmp/sber_tm_smoke.pdf').read_bytes()); "
        "print('verdict=', r.get('verdict')); "
        "print('flags=', r.get('flags')); "
        "d=r.get('details') or {}; "
        "print('hard=', d.get('hard_count'), d.get('engine'))\""
    ))

sftp.close()
ssh.close()
print("DEPLOYED")
