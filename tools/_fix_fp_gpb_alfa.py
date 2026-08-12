# -*- coding: utf-8 -*-
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


# Upload sample PDFs for remote smoke
samples = {
    "alfa_card.pdf": r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа\альфа карта.pdf",
    "alfa_sbp.pdf": r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа\pdf (1).pdf",
    "gpb_receipt.pdf": r"C:\Users\fanis\OneDrive\Desktop\чеки\газпромбанк оригинал\receipt6206788322134989778.pdf",
}
remote_dir = "/tmp/pdfbot_smoke"
run(f"mkdir -p {remote_dir}")
for name, local in samples.items():
    sftp.put(local, f"{remote_dir}/{name}")
    print("uploaded", name)

# Deploy critical detector files that fix routing/FP
files = [
    "detector/profiles.py",
    "detector/__init__.py",
    "detector/gazprombank.py",
    "detector/gpb_profiles.py",
    "detector/gpb_v1/stages.py",
    "detector/gpb_v1/engine.py",
    "detector/gpb_v1/rollout.py",
    "detector/hardening_v2/g_graph_003.py",
    "detector/hardening_v2/global_rules.py",
]
HERE = os.getcwd()
for rel in files:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.exists(local):
        print("SKIP missing", rel)
        continue
    remote = f"{cfg.BOT_DIR}/{rel}"
    # ensure dir
    parts = remote.rsplit("/", 1)[0].strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            sftp.mkdir(cur)
    sftp.put(local, remote)
    print("OK", rel)

print(run(f"cd {cfg.BOT_DIR} && python3 -m py_compile detector/profiles.py detector/gazprombank.py"))

smoke = f"""
cd {cfg.BOT_DIR} && PYTHONPATH=. python3 - <<'PY'
from pathlib import Path
from detector import route
from detector import profiles
import fitz
for name in ['alfa_card.pdf','alfa_sbp.pdf','gpb_receipt.pdf']:
    p=Path('/tmp/pdfbot_smoke')/name
    b=p.read_bytes()
    doc=fitz.open(stream=b,filetype='pdf')
    text=''.join(x.get_text() for x in doc)
    prod=doc.metadata.get('producer') or ''
    doc.close()
    prof,sc=profiles.identify(text,prod)
    bank,r,_=route(b)
    d=r.get('details') or {{}}
    print(name, '-> identify', (prof or {{}}).get('key'), '| route', bank, r.get('verdict'), r.get('score'), d.get('engine'))
    for f in (r.get('flags') or [])[:2]:
        print(' ', str(f)[:140])
PY
"""
print(run(smoke, timeout=180))
print(run("systemctl restart pdfbot"))
import time; time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
sftp.close(); ssh.close()
print("done")
