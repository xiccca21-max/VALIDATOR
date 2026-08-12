import os
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deploy_config as cfg

HERE = os.getcwd()
FILES = [
    "bot.py",
    "detector/tbank.py",
    "detector/tbank_legacy.py",
    "detector/tbank_v6/__init__.py",
    "detector/tbank_v6/types.py",
    "detector/tbank_v6/rules.py",
    "detector/tbank_v6/known_signatures.py",
    "detector/tbank_v6/verdict.py",
    "detector/tbank_v6/stages.py",
    "detector/tbank_v6/engine.py",
    "detector/tbank_v6/explain.py",
    "detector/tbank_sbp_content.py",
    "detector/tbank_sbp_epoch_reuse.py",
    "detector/tbank_keywords_generation.py",
    "detector/tbank_info_keywords_lex.py",
    "detector/tbank_jasper_profile.py",
    "detector/tbank_deflate_profile.py",
    "detector/tbank_font_cid_closure.py",
    "detector/tbank_receipt_format.py",
    "detector/tbank_reassembled_subset.py",
    "detector/tbank_id_reuse.py",
    "detector/tbank_stream_integrity.py",
    "detector/tbank_font_table_integrity.py",
    "detector/tbank_stream_serializer.py",
    "detector/tbank_flate_profile.py",
    "detector/font_layers.py",
    "detector/tbank_spec.py",
    "detector/tbank_text_layout_fingerprint.py",
    "detector/java_deflater.py",
    "detector/tbank_sbp_geometry.py",
    "detector/tbank_glyph_atlas.py",
    "detector/tbank_glyph_slot_transplant.py",
    "detector/tbank_used_glyph_integrity.py",
    "detector/tbank_glyph_atlas.json",
    "detector/sbp_cipher.py",
    "detector/tbank_font_rebuilder.py",
]

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode(errors="replace")


def ensure_remote_dir(path: str) -> None:
    parts = path.strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            sftp.mkdir(cur)


print(f"Connecting to {cfg.HOST} ...")
ensure_remote_dir(f"{cfg.BOT_DIR}/detector/tbank_v6")
ensure_remote_dir(f"{cfg.BOT_DIR}/detector/atlas_data")
for rel in FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    remote = f"{cfg.BOT_DIR}/{rel}"
    sftp.put(local, remote)
    print(f"OK {rel}")

atlas_dir = os.path.join(HERE, "detector", "atlas_data")
remote_atlas = f"{cfg.BOT_DIR}/detector/atlas_data"
for name in os.listdir(atlas_dir):
    if name.endswith(".json"):
        sftp.put(os.path.join(atlas_dir, name), f"{remote_atlas}/{name}")
        print(f"OK detector/atlas_data/{name}")

java_dir = os.path.join(HERE, "tools", "java_deflater")
remote_java = f"{cfg.BOT_DIR}/tools/java_deflater"
ensure_remote_dir(f"{cfg.BOT_DIR}/tools")
ensure_remote_dir(remote_java)
for name in os.listdir(java_dir):
    if name.endswith((".java", ".class")):
        sftp.put(os.path.join(java_dir, name), f"{remote_java}/{name}")
        print(f"OK tools/java_deflater/{name}")
print(run(f"cd {remote_java} && javac CanonicalDeflater.java 2>&1 || true"))

print("Remote compile...")
print(run(
    f"cd {cfg.BOT_DIR} && python3 -m py_compile "
    + " ".join(FILES)
))

print("Server tbank shim:")
print(run(f"cat {cfg.BOT_DIR}/detector/tbank.py"))

print("Restarting pdfbot...")
print(run("systemctl restart pdfbot"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print(run("journalctl -u pdfbot -n 5 --no-pager"))

sftp.close()
ssh.close()
print("Done")
