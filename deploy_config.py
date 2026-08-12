"""
Shared deploy connection helper.
"""
import os
import paramiko

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deploy.env")


def _load_env() -> None:
    if not os.path.exists(_ENV_FILE):
        return
    with open(_ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

HOST = os.getenv("PDFBOT_HOST", "")
USER = os.getenv("PDFBOT_USER", "root")
SSH_KEY = os.getenv("PDFBOT_SSH_KEY", "")
PASSWORD = os.getenv("PDFBOT_PASSWORD", "")
BOT_DIR = os.getenv("PDFBOT_DIR", "/root/pdf-checker-bot")


def connect(timeout: int = 20) -> paramiko.SSHClient:
    if not HOST:
        raise RuntimeError("PDFBOT_HOST is not set (create .deploy.env)")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_path = os.path.expanduser(SSH_KEY) if SSH_KEY else ""
    if key_path and os.path.exists(key_path):
        key = paramiko.Ed25519Key.from_private_key_file(key_path)
        ssh.connect(HOST, username=USER, pkey=key, timeout=timeout,
                    banner_timeout=60, auth_timeout=60,
                    look_for_keys=False, allow_agent=False)
    elif PASSWORD:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=timeout,
                    banner_timeout=60, auth_timeout=60)
    else:
        raise RuntimeError("No SSH key or password configured")
    return ssh
