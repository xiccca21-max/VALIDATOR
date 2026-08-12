#!/usr/bin/env python3
"""Deploy Alfa Oracle full-deflate provenance HARD + Java Deflater(6)."""

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
EXTRA = [
    "detector/java_deflater.py",
    "detector/alfa.py",
    "detector/__init__.py",
    "detector/hardening_v2/verdict_merge.py",
]
PACKAGE_DIR = HERE / "detector" / "alfa_v2"
JAVA_DIR = HERE / "tools" / "java_deflater"
FAKE = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\alfa_sbp_015818.pdf")


def collect_package() -> list[str]:
    rels: list[str] = []
    for path in PACKAGE_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".py", ".json"}:
            rels.append(str(path.relative_to(HERE)).replace("\\", "/"))
    return sorted(rels)


ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 300) -> str:
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


all_files = EXTRA + collect_package()
print(f"Connecting to {cfg.HOST} ...")
ensure_dir(f"{cfg.BOT_DIR}/detector/alfa_v2/atlas_data")
ensure_dir(f"{cfg.BOT_DIR}/tools/java_deflater")

for rel in all_files:
    local = HERE / rel.replace("/", os.sep)
    remote = f"{cfg.BOT_DIR}/{rel}"
    ensure_dir(os.path.dirname(remote).replace("\\", "/"))
    sftp.put(str(local), remote)
    print(f"OK {rel}")

for name in sorted(JAVA_DIR.iterdir()):
    if name.suffix.lower() in {".java", ".class"}:
        remote = f"{cfg.BOT_DIR}/tools/java_deflater/{name.name}"
        sftp.put(str(name), remote)
        print(f"OK tools/java_deflater/{name.name}")

if FAKE.is_file():
    remote_fake = f"{cfg.BOT_DIR}/_smoke_alfa_sbp_015818.pdf"
    sftp.put(str(FAKE), remote_fake)
    print(f"OK smoke fake -> {remote_fake}")

print("java:", run("java -version 2>&1 | head -3"))
print("recompile CanonicalDeflater:", run(f"cd {cfg.BOT_DIR}/tools/java_deflater && javac CanonicalDeflater.java 2>&1 || true"))

py_files = [f for f in all_files if f.endswith(".py")]
print("Remote compile...")
print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile " + " ".join(py_files)))

print("Restart pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))

print("Remote smoke...")
print(
    run(
        f"cd {cfg.BOT_DIR} && JAVA_HOME=${{JAVA_HOME:-}} python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "from detector import route\n"
        "from detector.java_deflater import java_deflate, _java_bin\n"
        "print('java_bin', _java_bin())\n"
        "probe = java_deflate(b'hello oracle deflate probe')\n"
        "print('java_deflate_ok', probe is not None, 'len', None if probe is None else len(probe))\n"
        "fake = Path('_smoke_alfa_sbp_015818.pdf')\n"
        "if fake.is_file():\n"
        "    bank, r, _ = route(fake.read_bytes())\n"
        "    d = r.get('details') or {}\n"
        "    print('fake', r.get('verdict'), 'engine', d.get('engine'), 'rollout', d.get('rollout_mode'))\n"
        "    print('hard_count', d.get('hard_count'), 'known', d.get('known_fake_count'))\n"
        "    for f in (r.get('flags') or [])[:5]:\n"
        "        print(' ', f[:160])\n"
        "    print('downgraded', d.get('v2_downgraded_diagnostic_fake'))\n"
        "else:\n"
        "    print('smoke fake missing')\n"
        "PY"
    )
)

sftp.close()
ssh.close()
print("Done — Oracle full deflate provenance deployed")
