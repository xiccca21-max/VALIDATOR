"""Deploy VTB v2 known-fake production path fix to pdfbot."""
import os
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "bot.py",
    "detector/__init__.py",
    "detector/reputation.py",
    "detector/vtb.py",
    "detector/vtb_known_hashes.py",
    "detector/hardening_v2/verdict_merge.py",
    "detector/vtb_v1/rollout.py",
    "detector/vtb_v2/__init__.py",
    "detector/vtb_v2/types.py",
    "detector/vtb_v2/rules.py",
    "detector/vtb_v2/verdict.py",
    "detector/vtb_v2/explain.py",
    "detector/vtb_v2/engine.py",
    "detector/vtb_v2/stages.py",
    "detector/vtb_v2/rollout.py",
    "detector/vtb_v2/known_signatures.py",
    "detector/vtb_v2/subtypes.py",
    "detector/vtb_v2/sbp.py",
    "detector/vtb_v2/signatures.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 180) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


def ensure_dir(path: str) -> None:
    parts = path.strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            sftp.mkdir(cur)


print(f"Connecting to {cfg.HOST} ...")
ensure_dir(f"{cfg.BOT_DIR}/detector/vtb_v2")
ensure_dir(f"{cfg.BOT_DIR}/detector/vtb_v1")
ensure_dir(f"{cfg.BOT_DIR}/detector/hardening_v2")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.isfile(local):
        print(f"SKIP missing {rel}")
        continue
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Force VTB rollout=100 ...")
print(run(
    "mkdir -p /etc/systemd/system/pdfbot.service.d && "
    "printf '[Service]\\n"
    "Environment=VTB_V2_ROLLOUT=100\\n"
    "Environment=VTB_V1_ROLLOUT=100\\n' "
    "> /etc/systemd/system/pdfbot.service.d/vtb-v2.conf && "
    "systemctl daemon-reload"
))

print("Remote compile + smoke ...")
smoke = run(
    f"cd {cfg.BOT_DIR} && "
    f"./venv/bin/python - <<'PY'\n"
    "import hashlib\n"
    "from detector import route\n"
    "from detector.vtb_known_hashes import VTB_KNOWN_FAKE_FILE_SHA256, check_vtb_known_file_hash\n"
    "from detector.reputation import KNOWN_FAKE_BY_SHA256, check_known_fake\n"
    "print('registry', len(VTB_KNOWN_FAKE_FILE_SHA256), len(KNOWN_FAKE_BY_SHA256))\n"
    "assert len(VTB_KNOWN_FAKE_FILE_SHA256)==2\n"
    "assert len(KNOWN_FAKE_BY_SHA256)==2\n"
    "print('imports_ok')\n"
    "PY"
)
print(smoke)

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run(
    "systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep -E 'VTB_|ROLLOUT' || true"
))

sftp.close()
ssh.close()
print("Done — VTB known-fake production path deployed")
