# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

ssh = cfg.connect()
sftp = ssh.open_sftp()

def run(cmd, timeout=180):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")

sftp.put(
    os.path.join(os.getcwd(), "tools", "_remote_smoke_body.py"),
    "/tmp/pdfbot_smoke_body.py",
)
print(run("systemctl cat pdfbot 2>/dev/null | sed -n '1,50p'"))
print("--- which python ---")
print(run(
    "systemctl show pdfbot -p ExecStart --no-pager; "
    "ls /root/pdf-checker-bot/.venv/bin/python 2>/dev/null; "
    "ls /root/pdf-checker-bot/venv/bin/python 2>/dev/null"
))
print("--- smoke ---")
print(run(
    "PY=$(systemctl show pdfbot -p ExecStart --value | awk '{print $1}'); "
    "echo EXEC=$PY; "
    "cd /root/pdf-checker-bot && PYTHONPATH=. \"$PY\" /tmp/pdfbot_smoke_body.py"
))
sftp.close()
ssh.close()
