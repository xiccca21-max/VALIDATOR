import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_config as cfg

files = [
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf"),
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf"),
]

ssh = cfg.connect()
sftp = ssh.open_sftp()
for p in files:
    sftp.put(str(p), f"/tmp/{p.name}")

remote = f"""
import sys
sys.path.insert(0, '{cfg.BOT_DIR}')
from pathlib import Path
from detector.ozon import analyze as oz
from detector.tbank import analyze as tb
from detector.reputation import file_hash
for name in {repr([f.name for f in files])}:
    b = Path('/tmp/' + name).read_bytes()
    h = file_hash(b)
    r = oz(b, h) if 'ozon' in name.lower() else tb(b, h)
    print(name, '->', r.get('verdict'), '|', (r.get('flags') or [''])[0][:70])
"""
with sftp.open("/tmp/_check.py", "w") as f:
    f.write(remote)

def run(cmd, timeout=120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")

print(run("python3 /tmp/_check.py"))
sftp.close()
ssh.close()
