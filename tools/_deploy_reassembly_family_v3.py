"""Deploy tbank_reassembly_family_v3 to Aeza production."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
FILES = [
    "detector/tbank_reassembly_family_v3.py",
    "detector/glyf_fingerprint.py",
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
    if not local.is_file():
        raise SystemExit(f"missing {rel}")
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(str(local), remote)
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && venv/bin/python -m py_compile "
    + " ".join(FILES)
))
print(run("systemctl restart pdfbot pdfmail"))
time.sleep(3)
print("services:", run("systemctl is-active pdfbot pdfmail").strip())

# smoke: upload fake 17
smoke = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt_21.07.2026 (17).pdf")
with sftp.file("/tmp/tbank_v3_smoke.pdf", "wb") as f:
    f.write(smoke.read_bytes())
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python -c "
    "\"from pathlib import Path; from detector.tbank import analyze, VALIDATOR_VERSION; "
    "r=analyze(Path('/tmp/tbank_v3_smoke.pdf').read_bytes()); "
    "cs=[x[1:x.index(']')] for x in (r.get('flags') or []) if x.startswith('[')]; "
    "print('version', VALIDATOR_VERSION); "
    "print('verdict', r.get('verdict')); "
    "print('family', 'TBANK_REASSEMBLY_FAMILY_V3' in cs); "
    "print('cmap', 'TBANK_SUBSET_CMAP_NOT_MINIMAL' in cs); "
    "print('w', 'TBANK_W_ARRAY_NOT_MINIMAL' in cs); "
    "print(cs[:8])\""
))

sftp.close()
ssh.close()
print("DEPLOYED")
