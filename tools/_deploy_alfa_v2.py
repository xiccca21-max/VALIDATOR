#!/usr/bin/env python3
"""Deploy Alfa v2 production cutover (no shadow)."""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = Path(os.getcwd())
FILES = [
    "bot.py",
    "detector/__init__.py",
    "detector/alfa.py",
    "detector/profiles.py",
    "detector/hardening_v2/verdict_merge.py",
    "detector/alfa_v1/rollout.py",
]

PACKAGE_DIR = HERE / "detector" / "alfa_v2"


def collect_package() -> list[str]:
    rels: list[str] = []
    for path in PACKAGE_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".py", ".json", ".db"}:
            # Skip local runtime DBs — recreate on server.
            if path.suffix.lower() == ".db":
                continue
            rels.append(str(path.relative_to(HERE)).replace("\\", "/"))
    return sorted(rels)


ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 180) -> str:
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


all_files = FILES + collect_package()
print(f"Connecting to {cfg.HOST} ...")
ensure_dir(f"{cfg.BOT_DIR}/detector/alfa_v2/atlas_data")

for rel in all_files:
    local = HERE / rel.replace("/", os.sep)
    remote = f"{cfg.BOT_DIR}/{rel}"
    remote_dir = os.path.dirname(remote).replace("\\", "/")
    ensure_dir(remote_dir)
    sftp.put(str(local), remote)
    print(f"OK {rel}")

print("Force ALFA_V1_ROLLOUT=full (no shadow) ...")
print(
    run(
        "mkdir -p /etc/systemd/system/pdfbot.service.d && "
        "printf '[Service]\\nEnvironment=ALFA_V1_ROLLOUT=full\\n' > "
        "/etc/systemd/system/pdfbot.service.d/alfa-v1.conf && "
        "systemctl daemon-reload"
    )
)

py_files = [f for f in all_files if f.endswith(".py")]
print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile " + " ".join(py_files)))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(
    run(
        "systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep ALFA || true"
    )
)

# remote smoke on uploaded fakes if present; otherwise import check
print("Remote import smoke...")
print(
    run(
        f"cd {cfg.BOT_DIR} && python3 - <<'PY'\n"
        "from detector.alfa import analyze, VALIDATOR_VERSION\n"
        "from detector.alfa_v2.engine import analyze as a2\n"
        "print('alfa', VALIDATOR_VERSION)\n"
        "print('engine ok', callable(analyze), callable(a2))\n"
        "PY"
    )
)

sftp.close()
ssh.close()
print("Done — Alfa v2 production, rollout=full")
