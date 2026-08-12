import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import deploy_config as cfg

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=90):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return (o.read() + e.read()).decode(errors="replace")


script = r"""
import os
from pathlib import Path
from detector import route as route_bank
from detector.sparse9_v1.rollout import master_rollout_mode, bank_rollout_mode
print('SPARSE9_V1_ROLLOUT', os.environ.get('SPARSE9_V1_ROLLOUT'))
print('modes', master_rollout_mode(), bank_rollout_mode('raif'))
n,r,_=route_bank(Path('/tmp/raif_00118_fake.pdf').read_bytes())
d=r.get('details') or {}
print(n, r.get('verdict'), r.get('score'))
print('engine', d.get('engine'), d.get('validator_engine'))
sh=d.get('sparse9_v1_shadow') or {}
print('shadow_meta', sh.get('mode'), 'v1', sh.get('v1_verdict'), 'legacy', sh.get('legacy_verdict'))
print(r.get('flags')[:4])
"""
with sftp.file("/tmp/smoke_raif_00118.py", "w") as f:
    f.write(script)

print(run(
    "bash -lc "
    "'export $(systemctl show pdfbot -p Environment --value); "
    "cd /root/pdf-checker-bot && PYTHONPATH=. venv/bin/python /tmp/smoke_raif_00118.py'"
))
sftp.close()
ssh.close()
