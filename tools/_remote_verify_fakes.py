import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_config as cfg

ssh = cfg.connect()
sftp = ssh.open_sftp()
PY = f"{cfg.BOT_DIR}/venv/bin/python"

def run(cmd, timeout=180):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")

files = [
    ("ozon_fake.pdf", r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf"),
    ("tbank_fake.pdf", r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf"),
]
for remote_name, local in files:
    p = Path(local)
    if p.exists():
        with sftp.open(f"/tmp/{remote_name}", "wb") as f:
            f.write(p.read_bytes())

script = f"""import sys
sys.path.insert(0, '{cfg.BOT_DIR}')
from pathlib import Path
from detector.profiles import identify, analyze_for
from detector.reputation import file_hash
import fitz

for path in ['/tmp/ozon_fake.pdf', '/tmp/tbank_fake.pdf']:
    if not Path(path).exists():
        continue
    b = Path(path).read_bytes()
    h = file_hash(b)
    d = fitz.open(stream=b, filetype='pdf')
    text = d[0].get_text()
    pr = (d.metadata or {{}}).get('producer', '')
    d.close()
    prof, _ = identify(text, pr)
    key = prof['key'] if prof else '?'
    r = analyze_for(key, b, h)
    print(path, 'bank=', key, 'verdict=', r.get('verdict'))
    for fl in (r.get('flags') or [])[:2]:
        print(' ', fl[:100])
"""
with sftp.open("/tmp/_verify.py", "w") as f:
    f.write(script)
print(run(f"{PY} /tmp/_verify.py"))
ssh.close()
