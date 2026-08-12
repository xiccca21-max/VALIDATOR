import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import fitz
from detector.profiles import reload_profiles, analyze, identify
from detector.sbp_cipher import extract_sbp_opid, validate_nspk_sbp_cipher
from detector.verdict import is_forgery_flag

reload_profiles()
CHEKI = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
SPECS = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\detector\bank_specs")

# spec settings
spec_sbp = {}
for sp in SPECS.glob("*.json"):
    try:
        d = json.loads(sp.read_text(encoding="utf-8"))
        spec_sbp[d.get("key")] = {
            "sbp_cipher": d.get("sbp_cipher", True),
            "producers": d.get("native_producers", []),
            "samples": d.get("sample_count"),
        }
    except Exception:
        pass

by_bank = defaultdict(lambda: {
    "n": 0, "producers": set(), "cores": set(), "pos17": set(),
    "sep18": set(), "cipher_flags": 0, "soft": 0, "hard": 0, "noncleans": [],
})

for f in sorted(CHEKI.rglob("*.pdf")):
    b = f.read_bytes()
    try:
        doc = fitz.open(stream=b, filetype="pdf")
        prod = doc.metadata.get("producer", "") or ""
        txt = "".join(p.get_text() for p in doc)
        doc.close()
    except Exception:
        prod, txt = "", ""
    prof, _ = identify(txt, prod)
    key = prof["key"] if prof else "unknown"
    r = analyze(b, f.stem)
    rec = by_bank[key]
    rec["n"] += 1
    rec["producers"].add(prod[:40])
    opid = extract_sbp_opid(txt)
    if opid and len(opid) == 32:
        rec["cores"].add(opid[22:27])
        rec["pos17"].add(opid[16])
        rec["sep18"].add(opid[17])
    fl = r.get("flags", [])
    forg = [x for x in fl if is_forgery_flag(x)]
    soft = [x for x in fl if not is_forgery_flag(x)]
    rec["hard"] += len(forg)
    rec["soft"] += len(soft)
    if r["verdict"] != "ЧИСТО":
        rec["noncleans"].append((f.name, r["verdict"], r["score"]))

print(f"{'bank':<12} {'n':>3} {'sbp?':<5} {'cores':<20} {'pos17':<8} {'hard':>4} {'soft':>4}  noncln")
for key in sorted(by_bank):
    rec = by_bank[key]
    s = spec_sbp.get(key, {})
    sbp = s.get("sbp_cipher", "-")
    print(f"{ascii(key):<12} {rec['n']:>3} {str(sbp):<5} "
          f"{ascii(str(sorted(rec['cores']))):<20} {ascii(str(sorted(rec['pos17']))):<8} "
          f"{rec['hard']:>4} {rec['soft']:>4}  {len(rec['noncleans'])}")
    for nc in rec["noncleans"]:
        print("      NONCLEAN", ascii(nc[0]), nc[1], nc[2])

print()
print("=== producers per bank ===")
for key in sorted(by_bank):
    print(ascii(key), "->", ascii(str(sorted(by_bank[key]["producers"]))))
