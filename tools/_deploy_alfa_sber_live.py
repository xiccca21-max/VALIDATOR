"""Deploy Alfa new-SBP profile + Sber exact-profile fixes to Aeza."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")

FILES = [
    # Alfa — unknown bank5/suffix → CLEAN + observe
    "detector/alfa_v2/unconfirmed_profiles.py",
    "detector/alfa_v2/sbp.py",
    "detector/alfa_v2/rules.py",
    "detector/alfa_v2/stages.py",
    "detector/alfa_v2/atlas_data/alfa_new_sbp_profile_observations.json",
    # Sber — exact sbp_outgoing HARD contracts
    "detector/sber_v2/sbp_exact_profile.py",
    "detector/sber_v2/rules.py",
    "detector/sber_v2/stages.py",
    "detector/sber_v2/profile_gates.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


for d in (
    f"{cfg.BOT_DIR}/detector/alfa_v2/atlas_data",
    f"{cfg.BOT_DIR}/detector/sber_v2",
):
    run(f"mkdir -p {d}")

missing = []
for rel in FILES:
    local = HERE / rel.replace("/", os.sep)
    if not local.is_file():
        missing.append(rel)
        print("MISSING", rel)
        continue
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(str(local), remote)
    print("OK", rel)

if missing:
    raise SystemExit(f"missing files: {missing}")

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    "detector/alfa_v2/unconfirmed_profiles.py "
    "detector/alfa_v2/sbp.py "
    "detector/alfa_v2/rules.py "
    "detector/alfa_v2/stages.py "
    "detector/sber_v2/sbp_exact_profile.py "
    "detector/sber_v2/rules.py "
    "detector/sber_v2/stages.py "
    "detector/sber_v2/profile_gates.py"
))

print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

# remote smoke: 37850 if present locally
smoke = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\37850.pdf")
if smoke.is_file():
    with sftp.file("/tmp/alfa_37850.pdf", "wb") as f:
        f.write(smoke.read_bytes())
    print(run(
        "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
        "\"from pathlib import Path; from detector.alfa import analyze; "
        "r=analyze(Path('/tmp/alfa_37850.pdf').read_bytes()); "
        "d=r.get('details') or {}; "
        "obs=[x for x in (d.get('ignored_observations') or []) if 'NEW_SBP' in x]; "
        "print('verdict=', r.get('verdict')); "
        "print('obs=', obs); "
        "print('manual=', d.get('manual_review_required'))\""
    ))

sftp.close()
ssh.close()
print("DEPLOYED")
