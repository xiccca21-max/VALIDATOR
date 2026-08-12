# -*- coding: utf-8 -*-
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "mail_server.py",
    "detector/email_check.py",
    "detector/mailbox.py",
    "detector/hardening_v2/verdict_merge.py",
    "detector/__init__.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


print(f"Connecting to {cfg.HOST} ...")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.exists(local):
        print("SKIP", rel)
        continue
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print("OK", rel)

print(run(
    f"cd {cfg.BOT_DIR} && /root/pdf-checker-bot/venv/bin/python -m py_compile "
    "mail_server.py detector/email_check.py detector/mailbox.py "
    "detector/hardening_v2/verdict_merge.py detector/__init__.py"
))

# Critical: pdfmail keeps old modules in memory until restart
print("Restart pdfmail + pdfbot...")
print(run("systemctl restart pdfmail pdfbot"))
time.sleep(4)
print("pdfbot:", run("systemctl is-active pdfbot").strip())
print("pdfmail:", run("systemctl is-active pdfmail").strip())
print(run(
    "cd /root/pdf-checker-bot && PYTHONPATH=. /root/pdf-checker-bot/venv/bin/python -c "
    "'from detector.hardening_v2.verdict_merge import has_decisive_evidence; "
    "from detector import route; print(\"import OK\", has_decisive_evidence.__name__)'"
))
print(run("journalctl -u pdfmail -n 15 --no-pager"))
sftp.close()
ssh.close()
print("Done")
