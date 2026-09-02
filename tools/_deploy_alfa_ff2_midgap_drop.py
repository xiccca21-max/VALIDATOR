"""Deploy Alfa FontFile2 midgap drop: ignore ALFA_ORACLE_FF2_SIZE_MIDGAP."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/alfa_v2/fonts.py",
    "detector/alfa_v2/rules.py",
]

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
print("remote grep:")
print(run(
    "grep -n ALFA_ORACLE_FF2_SIZE_MIDGAP "
    f"{cfg.BOT_DIR}/detector/alfa_v2/fonts.py "
    f"{cfg.BOT_DIR}/detector/alfa_v2/rules.py || true"
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

remote_py = (
    "from detector.alfa_v2.rules import HARD_CODES, IGNORED_CODES\n"
    "code = 'ALFA_ORACLE_FF2_SIZE_MIDGAP'\n"
    "print('hard', code in HARD_CODES)\n"
    "print('ignored', code in IGNORED_CODES)\n"
)
with sftp.file("/tmp/_check_alfa_midgap.py", "w") as f:
    f.write(remote_py)
print(run(f"cd {cfg.BOT_DIR} && PYTHONPATH=. venv/bin/python /tmp/_check_alfa_midgap.py"))

sftp.close()
ssh.close()
print("DEPLOYED")
