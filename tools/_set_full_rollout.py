import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_config as cfg

ENVS = """
[Service]
Environment=OZON_V1_ROLLOUT=full
Environment=SBER_V1_ROLLOUT=full
Environment=ALFA_V1_ROLLOUT=full
Environment=VTB_V1_ROLLOUT=full
Environment=GPB_V1_ROLLOUT=full
Environment=SPARSE9_V1_ROLLOUT=full
""".strip()

ssh = cfg.connect()

def run(cmd, timeout=120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")

print(run(
    "mkdir -p /etc/systemd/system/pdfbot.service.d && "
    "cat > /etc/systemd/system/pdfbot.service.d/v1-full.conf << 'EOF'\n"
    + ENVS + "\nEOF\n"
    "systemctl daemon-reload && systemctl restart pdfbot"
))
import time; time.sleep(3)
print("active:", run("systemctl is-active pdfbot").strip())
print(run("systemctl show pdfbot -p Environment --no-pager | tr ' ' '\\n' | grep ROLLOUT"))
ssh.close()
