"""Deploy VTB card HARD rules + Ozon G101 cross-bank catch."""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    "detector/vtb_v2/rules.py",
    "detector/vtb_v2/subtypes.py",
    "detector/vtb_v2/engine.py",
    "detector/ozon_sbp_content.py",
    "detector/ozon_v1/engine.py",
]

FAKE_LOCAL = os.path.join(
    os.path.expanduser("~"),
    "Downloads",
    "Telegram Desktop",
    "receipt_23.07.2026 5.pdf",
)

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


print(f"Connecting to {cfg.HOST} ...")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.isfile(local):
        print(f"SKIP missing {rel}")
        continue
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

if os.path.isfile(FAKE_LOCAL):
    remote_fake = f"{cfg.BOT_DIR}/_smoke_vtb_card_fake.pdf"
    sftp.put(FAKE_LOCAL, remote_fake)
    print(f"OK smoke fake -> {remote_fake}")
else:
    remote_fake = ""
    print("WARN local fake missing, skip upload")

print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && ./venv/bin/python -m py_compile " + " ".join(FILES)))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot").strip())

if remote_fake:
    smoke = run(
        f"cd {cfg.BOT_DIR} && ./venv/bin/python - <<'PY'\n"
        "from pathlib import Path\n"
        "from detector import route\n"
        "from detector.vtb_v2.engine import analyze, VALIDATOR_VERSION\n"
        "pdf = Path('_smoke_vtb_card_fake.pdf').read_bytes()\n"
        "print('vtb_version', VALIDATOR_VERSION)\n"
        "r = analyze(pdf)\n"
        "print('direct', r['verdict'], r['details'].get('subtype'), r['flags'][:3])\n"
        "name, payload, _ = route(pdf)\n"
        "print('route', name, payload.get('verdict'), payload.get('details', {}).get('subtype'))\n"
        "print('hard', (payload.get('details') or {}).get('hard_flags', [])[:5])\n"
        "PY"
    )
    print("SMOKE:\n", smoke)

sftp.close()
ssh.close()
print("Done")
