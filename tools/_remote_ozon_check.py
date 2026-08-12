import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg
from pathlib import Path

pdf = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf").read_bytes()

ssh = cfg.connect()
sftp = ssh.open_sftp()
with sftp.open("/tmp/ozon_950000.pdf", "wb") as f:
    f.write(pdf)


def run(cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


print("ROLLOUT:", run(
    "systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep OZON || true"
).strip())

remote_py = f"""import sys
sys.path.insert(0, '{cfg.BOT_DIR}')
from pathlib import Path
try:
    import fitz
    fitz_ok = True
except Exception as e:
    fitz_ok = False
    fitz_err = repr(e)
from detector.ozon import analyze
from detector.ozon_v1.engine import run_pipeline
from detector.reputation import file_hash
b = Path('/tmp/ozon_950000.pdf').read_bytes()
h = file_hash(b)
pipe = run_pipeline(b, h)
r = analyze(b, h)
print('fitz_ok=', fitz_ok)
if not fitz_ok:
    print('fitz_err=', fitz_err)
print('analysis_complete=', pipe.analysis_complete)
print('completed_checks=', pipe.completed_checks)
print('hard=', [f.code for f in pipe.hard_flags])
print('verdict=', r.get('verdict'))
print('flags=', (r.get('flags') or [])[:6])
shadow = (r.get('details') or {{}}).get('ozon_v1_shadow') or {{}}
print('rollout_mode=', shadow.get('mode'))
"""
with sftp.open("/tmp/_ozon_check.py", "w") as f:
    f.write(remote_py)
print(run("python3 /tmp/_ozon_check.py"))
sftp.close()
ssh.close()
