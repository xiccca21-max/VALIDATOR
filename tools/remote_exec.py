#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deploy_config as cfg


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/remote_exec.py <command>")
        return 2
    cmd = " ".join(sys.argv[1:])
    ssh = cfg.connect()
    try:
        _, out, err = ssh.exec_command(cmd, timeout=120)
        data = (out.read() + err.read()).decode("utf-8", "replace")
        print(data.strip())
    finally:
        ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
