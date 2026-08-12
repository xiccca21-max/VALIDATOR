#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deploy_config as cfg


def main() -> int:
    enabled = sys.argv[1] if len(sys.argv) > 1 else "0"
    channel = sys.argv[2] if len(sys.argv) > 2 else ""
    ssh = cfg.connect()
    try:
        cmd = (
            "python3 -c \"from pathlib import Path; "
            "p=Path('/root/pdf-checker-bot/.env'); "
            "txt=p.read_text(encoding='utf-8') if p.exists() else ''; "
            "lines=[ln for ln in txt.splitlines() if not ln.startswith('ARCHIVE_ENABLED=') and not ln.startswith('ARCHIVE_CHANNEL=')]; "
            f"lines.append('ARCHIVE_ENABLED={enabled}'); "
            f"lines.append('ARCHIVE_CHANNEL={channel}'); "
            "p.write_text('\\\\n'.join(lines)+'\\\\n', encoding='utf-8'); "
            "print('env updated')\""
        )
        _, out, err = ssh.exec_command(cmd, timeout=60)
        print((out.read() + err.read()).decode("utf-8", "replace").strip())
        _, out, err = ssh.exec_command("systemctl restart pdfbot && systemctl is-active pdfbot", timeout=60)
        print((out.read() + err.read()).decode("utf-8", "replace").strip())
    finally:
        ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
