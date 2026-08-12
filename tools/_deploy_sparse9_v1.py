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
    "detector/profiles.py",
    "detector/sparse9.py",
    "detector/sparse9_legacy.py",
    "detector/sparse9_profiles.py",
    "detector/sparse9_sbp_cipher.py",
    "detector/sparse9_v1/__init__.py",
    "detector/sparse9_v1/types.py",
    "detector/sparse9_v1/rules.py",
    "detector/sparse9_v1/verdict.py",
    "detector/sparse9_v1/explain.py",
    "detector/sparse9_v1/stages.py",
    "detector/sparse9_v1/engine.py",
    "detector/sparse9_v1/rollout.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
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
ensure_dir(f"{cfg.BOT_DIR}/detector/sparse9_v1")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Set SPARSE9_V1_ROLLOUT=shadow ...")
print(run(
    f"grep -q SPARSE9_V1_ROLLOUT /etc/systemd/system/pdfbot.service 2>/dev/null || "
    f"(mkdir -p /etc/systemd/system/pdfbot.service.d && "
    f"printf '[Service]\\nEnvironment=SPARSE9_V1_ROLLOUT=shadow\\n' > "
    f"/etc/systemd/system/pdfbot.service.d/sparse9-v1.conf && systemctl daemon-reload)"
))

print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile " + " ".join(FILES)))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run("systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep SPARSE9 || true"))

sftp.close()
ssh.close()
print("Done — Sparse9 v1 shadow mode active")
