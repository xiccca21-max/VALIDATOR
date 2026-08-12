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
    "detector/sber.py",
    "detector/sber_legacy.py",
    "detector/sber_profiles.py",
    "detector/sber_sbp_cipher.py",
    "detector/sber_v1/__init__.py",
    "detector/sber_v1/types.py",
    "detector/sber_v1/rules.py",
    "detector/sber_v1/verdict.py",
    "detector/sber_v1/explain.py",
    "detector/sber_v1/stages.py",
    "detector/sber_v1/engine.py",
    "detector/sber_v1/rollout.py",
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
ensure_dir(f"{cfg.BOT_DIR}/detector/sber_v1")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Set SBER_V1_ROLLOUT=shadow in service env...")
print(run(
    f"grep -q SBER_V1_ROLLOUT /etc/systemd/system/pdfbot.service 2>/dev/null || "
    f"(mkdir -p /etc/systemd/system/pdfbot.service.d && "
    f"printf '[Service]\\nEnvironment=SBER_V1_ROLLOUT=shadow\\n' > "
    f"/etc/systemd/system/pdfbot.service.d/sber-v1.conf && systemctl daemon-reload)"
))

print("Remote compile...")
print(run(
    f"cd {cfg.BOT_DIR} && python3 -m py_compile "
    + " ".join(FILES)
))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run("systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep SBER || true"))

sftp.close()
ssh.close()
print("Done — Sber v1 shadow mode active")
