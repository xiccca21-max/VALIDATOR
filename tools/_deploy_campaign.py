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
    "campaign/__init__.py",
    "campaign/config.py",
    "campaign/db.py",
    "campaign/identity.py",
    "campaign/service.py",
    "campaign/texts.py",
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
ensure_dir(f"{cfg.BOT_DIR}/campaign")
ensure_dir(f"{cfg.BOT_DIR}/data")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

print("Remote compile...")
print(run(
    f"cd {cfg.BOT_DIR} && python3 -m py_compile bot.py "
    "campaign/__init__.py campaign/config.py campaign/db.py "
    "campaign/identity.py campaign/service.py campaign/texts.py"
))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(4)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run("journalctl -u pdfbot -n 20 --no-pager"))

sftp.close()
ssh.close()
print("Done — campaign system deployed")
