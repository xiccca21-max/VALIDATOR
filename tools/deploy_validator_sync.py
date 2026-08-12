# -*- coding: utf-8 -*-
"""Sync changed detector modules + bot.py to pdf-checker VPS and restart.

Usage:
  python tools/deploy_validator_sync.py                 # full detector/ + bot.py
  python tools/deploy_validator_sync.py path1 path2     # specific files
  python tools/deploy_validator_sync.py --no-restart path.json
      # upload only (JSON pin sidecars hot-reload without killing in-flight checks)
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

HERE = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
sys.path.insert(0, str(HERE))
import deploy_config as cfg  # noqa: E402


def _collect_default() -> list[Path]:
    files: list[Path] = []
    bot = HERE / "bot.py"
    if bot.is_file():
        files.append(bot)
    det = HERE / "detector"
    for p in det.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in {".py", ".json", ".jsonl", ".db", ".txt"}:
            continue
        if "__pycache__" in p.parts:
            continue
        files.append(p)
    return files


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    no_restart = False
    if "--no-restart" in args:
        no_restart = True
        args = [a for a in args if a != "--no-restart"]

    if args:
        rels = [Path(a) for a in args]
        files = []
        for r in rels:
            p = r if r.is_absolute() else HERE / r
            if p.is_file():
                files.append(p)
            else:
                print("MISSING", p)
                return 1
    else:
        files = _collect_default()

    # Pin JSON sidecars are read on every check — restart not required.
    if not no_restart and files and all(p.suffix.lower() == ".json" for p in files):
        no_restart = True
        print("auto --no-restart (json-only upload)", flush=True)

    ssh = cfg.connect()
    sftp = ssh.open_sftp()

    def run(cmd: str, timeout: int = 180) -> str:
        _, o, e = ssh.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode(errors="replace")

    run(f"mkdir -p {cfg.BOT_DIR}/detector")
    n = 0
    skipped = 0
    for local in files:
        rel = local.relative_to(HERE).as_posix()
        remote = f"{cfg.BOT_DIR}/{rel}"
        remote_dir = remote.rsplit("/", 1)[0]
        run(f"mkdir -p {remote_dir}")
        local_hash = _sha256_file(local)
        remote_hash = run(f"sha256sum {remote} 2>/dev/null | awk '{{print $1}}'").strip()
        if remote_hash == local_hash:
            skipped += 1
            continue
        sftp.put(str(local), remote)
        n += 1
        if n % 25 == 0:
            print(f"... {n} files", flush=True)
    print(f"uploaded {n} files (skipped unchanged {skipped})", flush=True)

    if no_restart:
        print("skip restart (--no-restart)", flush=True)
    elif n == 0:
        print("skip restart (nothing uploaded)", flush=True)
    else:
        # Restart pdfbot only — avoid thrashing pdfmail on every pin-related deploy.
        print(run("systemctl restart pdfbot"), flush=True)
        time.sleep(3)
        print("services:", run("systemctl is-active pdfbot pdfmail").strip(), flush=True)
    sftp.close()
    ssh.close()
    print("DEPLOYED validator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
