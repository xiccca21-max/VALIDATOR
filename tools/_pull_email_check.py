# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

ssh = cfg.connect()
sftp = ssh.open_sftp()
sftp.get("/root/pdf-checker-bot/detector/email_check.py",
         os.path.join(os.getcwd(), "detector", "email_check.py"))
print("pulled email_check", os.path.getsize("detector/email_check.py"))

def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")

print(run("grep -nE 'route|has_decisive|verdict_merge|analyze|ImportError|from detector' /root/pdf-checker-bot/detector/email_check.py | head -80"))
print("--- bot email refs ---")
print(run("grep -nE 'email_check|mailbox|poll_mail|imap' /root/pdf-checker-bot/bot.py | head -40"))
print("--- find email worker ---")
print(run("ls /root/pdf-checker-bot/*.py /etc/systemd/system/*mail* /etc/systemd/system/*pdf* 2>/dev/null; systemctl list-units --type=service --all | grep -iE 'mail|pdf|imap' "))
sftp.close(); ssh.close()
