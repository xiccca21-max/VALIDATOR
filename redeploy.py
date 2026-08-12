import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import deploy_config as cfg

BOT_DIR = cfg.BOT_DIR
HERE = os.path.dirname(os.path.abspath(__file__))

ssh = cfg.connect()
sftp = ssh.open_sftp()


def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return (out + err).strip()


REL_FILES = [
    "detector/__init__.py",
    "detector/profiles.py",
    "detector/structure.py",
    "detector/pdf_forensics.py",
    "detector/font_layers.py",
    "detector/corpus_profiles.py",
    "detector/corpus_signals.py",
    "detector/explain.py",
    "detector/alfa.py",
    "detector/alfa_spec.py",
    "detector/alfa_profiles.py",
    "detector/alfa_invariants.py",
    "detector/alfa_invariants.json",
    "detector/alfa_sbp_cipher.py",
    "detector/alfa_sbp_extensions.json",
    "detector/tbank_sbp_cipher.py",
    "detector/tbank_sbp_extensions.json",
    "detector/tbank.py",
    "detector/tbank_template_profile.py",
    "detector/tbank_corpus_spec.py",
    "detector/glyf_fingerprint.py",
    "detector/glyf_reference.json",
    "detector/ff2_pool.py",
    "detector/sber.py",
    "detector/sber_legacy.py",
    "detector/sber_profiles.py",
    "detector/sber_sbp_cipher.py",
    "detector/sber_v1/__init__.py",
    "detector/sber_v1/types.py",
    "detector/sber_v1/rules.py",
    "detector/sber_v1/verdict.py",
    "detector/sber_v1/explain.py",
    "detector/sber_v1/stages.py",
    "detector/sber_v1/engine.py",
    "detector/sber_v1/rollout.py",
    "detector/ozon.py",
    "detector/ozon_legacy.py",
    "detector/ozon_profiles.py",
    "detector/ozon_sbp_cipher.py",
    "detector/ozon_v1/__init__.py",
    "detector/ozon_v1/types.py",
    "detector/ozon_v1/rules.py",
    "detector/ozon_v1/verdict.py",
    "detector/ozon_v1/explain.py",
    "detector/ozon_v1/stages.py",
    "detector/ozon_v1/engine.py",
    "detector/ozon_v1/rollout.py",
    "detector/vtb.py",
    "detector/vtb_legacy.py",
    "detector/vtb_profiles.py",
    "detector/vtb_sbp_cipher.py",
    "detector/vtb_v1/__init__.py",
    "detector/vtb_v1/types.py",
    "detector/vtb_v1/rules.py",
    "detector/vtb_v1/verdict.py",
    "detector/vtb_v1/explain.py",
    "detector/vtb_v1/stages.py",
    "detector/vtb_v1/engine.py",
    "detector/vtb_v1/rollout.py",
    "detector/gazprombank.py",
    "detector/gpb_legacy.py",
    "detector/gpb_profiles.py",
    "detector/gpb_sbp_cipher.py",
    "detector/gpb_v1/__init__.py",
    "detector/gpb_v1/types.py",
    "detector/gpb_v1/rules.py",
    "detector/gpb_v1/verdict.py",
    "detector/gpb_v1/explain.py",
    "detector/gpb_v1/stages.py",
    "detector/gpb_v1/engine.py",
    "detector/gpb_v1/rollout.py",
    "detector/sparse9.py",
    "detector/sparse9_legacy.py",
    "detector/sparse9_profiles.py",
    "detector/sparse9_sbp_cipher.py",
    "detector/sparse9_v1/__init__.py",
    "detector/sparse9_v1/types.py",
    "detector/sparse9_v1/rules.py",
    "detector/sparse9_v1/verdict.py",
    "detector/sparse9_v1/explain.py",
    "detector/sparse9_v1/stages.py",
    "detector/sparse9_v1/engine.py",
    "detector/sparse9_v1/rollout.py",
    "detector/sber_sbp_layout.py",
    "detector/symbol_library.py",
    "detector/font_authenticity.py",
    "detector/anti_edit.py",
    "detector/ff2_corpus.json",
    "detector/reputation.py",
    "detector/analytics.py",
    "detector/parser.py",
    "detector/generic_bank.py",
    "detector/full_bank.py",
    "detector/sbp_cipher.py",
    "detector/bank_channels.py",
    "detector/bank_spec_engine.py",
    "detector/forensics_profile.py",
    "detector/policy_v5.py",
    "detector/verdict.py",
    "detector/tbank_invariants.py",
    "detector/tbank_invariants.json",
    "detector/tbank_font_render.py",
    "detector/render_fingerprint.py",
    "detector/tbank_enroll.py",
    "detector/tbank_render_rows.json",
    "detector/bank_corpus.json",
    "bot.py",
]

print(f"Connecting to {cfg.HOST} ...")
run(f"mkdir -p {BOT_DIR}/detector/bank_specs")
run(f"mkdir -p {BOT_DIR}/detector/symbol_libraries")
run(f"mkdir -p {BOT_DIR}/detector/font_libraries")
run(f"mkdir -p {BOT_DIR}/detector/data/tbank_template")
print("Uploading detector files...")
for rel in REL_FILES:
    local = os.path.join(HERE, rel.replace("/", os.sep))
    if not os.path.isfile(local):
        raise FileNotFoundError(local)
    sftp.put(local, f"{BOT_DIR}/{rel}")
    print(f"  OK {rel}")

specs_dir = os.path.join(HERE, "detector", "bank_specs")
for name in sorted(os.listdir(specs_dir)):
    if name.endswith(".json"):
        rel = f"detector/bank_specs/{name}"
        sftp.put(os.path.join(specs_dir, name), f"{BOT_DIR}/{rel}")
        print(f"  OK {rel}")

sym_dir = os.path.join(HERE, "detector", "symbol_libraries")
if os.path.isdir(sym_dir):
    for name in sorted(os.listdir(sym_dir)):
        if name.endswith(".json"):
            rel = f"detector/symbol_libraries/{name}"
            sftp.put(os.path.join(sym_dir, name), f"{BOT_DIR}/{rel}")
            print(f"  OK {rel}")

font_dir = os.path.join(HERE, "detector", "font_libraries")
if os.path.isdir(font_dir):
    for name in sorted(os.listdir(font_dir)):
        if name.endswith(".json"):
            rel = f"detector/font_libraries/{name}"
            sftp.put(os.path.join(font_dir, name), f"{BOT_DIR}/{rel}")
            print(f"  OK {rel}")

tpl_dir = os.path.join(HERE, "detector", "data", "tbank_template")
if os.path.isdir(tpl_dir):
    for name in sorted(os.listdir(tpl_dir)):
        if name.endswith(".json"):
            rel = f"detector/data/tbank_template/{name}"
            sftp.put(os.path.join(tpl_dir, name), f"{BOT_DIR}/{rel}")
            print(f"  OK {rel}")

print("Restarting services...")
print(run("systemctl restart pdfbot"))
print(run("systemctl restart pdfmail"))
time.sleep(3)
print("pdfbot:", run("systemctl is-active pdfbot"))
print("pdfmail:", run("systemctl is-active pdfmail"))
print("Status pdfbot:")
print(run("systemctl status pdfbot --no-pager -l | head -15"))
print("Status pdfmail:")
print(run("systemctl status pdfmail --no-pager -l | head -15"))
print("Logs (pdfbot):")
print(run("journalctl -u pdfbot -n 8 --no-pager"))
print("Logs (pdfmail):")
print(run("journalctl -u pdfmail -n 8 --no-pager"))

sftp.close()
ssh.close()
print("\nDone!")
