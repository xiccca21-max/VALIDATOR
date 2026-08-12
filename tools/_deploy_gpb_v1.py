import os
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "detector/profiles.py",
    "detector/gazprombank.py",
    "detector/gpb_legacy.py",
    "detector/gpb_profiles.py",
    "detector/gpb_sbp_cipher.py",
    "detector/gpb_v1/__init__.py",
    "detector/gpb_v1/types.py",
    "detector/gpb_v1/rules.py",
    "detector/gpb_v1/verdict.py",
    "detector/gpb_v1/explain.py",
    "detector/gpb_v1/stages.py",
    "detector/gpb_v1/engine.py",
    "detector/gpb_v1/rollout.py",
    "detector/hardening_v2/g_graph_003.py",
    "detector/hardening_v2/global_rules.py",
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
ensure_dir(f"{cfg.BOT_DIR}/detector/gpb_v1")
ensure_dir(f"{cfg.BOT_DIR}/detector/hardening_v2")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Set GPB_V1_ROLLOUT=full ...")
print(run(
    "mkdir -p /etc/systemd/system/pdfbot.service.d && "
    "printf '[Service]\\nEnvironment=GPB_V1_ROLLOUT=full\\n' > "
    "/etc/systemd/system/pdfbot.service.d/gpb-v1.conf && "
    "systemctl daemon-reload"
))

print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile " + " ".join(FILES)))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run("systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep GPB || true"))

sftp.close()
ssh.close()
print("Done — GPB v1 full + latent revision HARD")
