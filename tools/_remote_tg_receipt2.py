import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_config as cfg

ssh = cfg.connect()
PY = f"{cfg.BOT_DIR}/venv/bin/python"
sftp = ssh.open_sftp()
local = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf")
with sftp.open("/tmp/tg_receipt2.pdf", "wb") as f:
    f.write(local.read_bytes())
script = f"""
import sys
sys.path.insert(0, '{cfg.BOT_DIR}')
from pathlib import Path
from detector.tbank import analyze
from detector.reputation import file_hash
b = Path('/tmp/tg_receipt2.pdf').read_bytes()
h = file_hash(b)
r = analyze(b, h)
print('hash', h[:12])
print('verdict', r.get('verdict'))
print('flags', (r.get('flags') or [])[:3])
"""
with sftp.open("/tmp/_chk.py", "w") as f:
    f.write(script)
_, o, e = ssh.exec_command(f"{PY} /tmp/_chk.py", timeout=120)
print((o.read()+e.read()).decode(errors='replace'))
ssh.close()
