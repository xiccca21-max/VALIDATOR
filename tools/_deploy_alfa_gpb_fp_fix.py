# -*- coding: utf-8 -*-
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "detector/profiles.py",
    "detector/alfa_v2/shell_clone.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=180):
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
for rel in FILES:
    ensure_dir(os.path.dirname(f"{cfg.BOT_DIR}/{rel}").replace("\\", "/"))
    sftp.put(os.path.join(HERE, rel.replace("/", os.sep)), f"{cfg.BOT_DIR}/{rel}")
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && /root/pdf-checker-bot/venv/bin/python -m py_compile "
    + " ".join(FILES)
))
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. /root/pdf-checker-bot/venv/bin/python "
    "/tmp/pdfbot_smoke_body.py"
))
sftp.close()
ssh.close()
print("done")
