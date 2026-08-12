import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_config as cfg

ssh = cfg.connect()

def run(cmd, timeout=120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")

script = f"""import sys
sys.path.insert(0, '{cfg.BOT_DIR}')
try:
    import fitz
    print('fitz_ok', fitz.version)
except Exception as e:
    print('fitz_fail', e)
from pathlib import Path
from detector.ozon_v1.engine import run_pipeline as oz_pipe
from detector.tbank_v6.engine import run_pipeline as tb_pipe
from detector.reputation import file_hash
for name in ['ozonbank_document_20260713182949.pdf', 'receipt (2).pdf']:
    b = Path('/tmp/' + name).read_bytes()
    h = file_hash(b)
    if 'ozon' in name:
        p = oz_pipe(b, h)
    else:
        p = tb_pipe(b, h)
    print(name, 'complete=', p.analysis_complete, 'hard=', [f.code for f in p.hard_flags][:3])
"""
sftp = ssh.open_sftp()
with sftp.open("/tmp/_diag.py", "w") as f:
    f.write(script)
sftp.close()
print(run("python3 /tmp/_diag.py"))
ssh.close()
