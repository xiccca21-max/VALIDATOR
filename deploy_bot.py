"""Deploy bot.py + explain module to server."""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import deploy_config as cfg

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = cfg.BOT_DIR

ssh = cfg.connect()
sftp = ssh.open_sftp()

for rel in ["bot.py", "check_history.py", "detector/explain.py"]:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    src = local
    if rel == "bot.py" and not os.path.isfile(src):
        src = os.path.join(HERE, "_bot_full_utf8.py")
    sftp.put(src, f"{BOT_DIR}/{rel}")
    print(f"OK {rel}")

_, stdout, _ = ssh.exec_command("systemctl restart pdfbot", timeout=30)
stdout.read()
time.sleep(2)
_, stdout, _ = ssh.exec_command("systemctl is-active pdfbot", timeout=15)
print("pdfbot:", stdout.read().decode().strip())

sftp.close()
ssh.close()
print("Done")
