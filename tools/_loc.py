import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import fitz
from detector.profiles import reload_profiles, analyze
from detector.verdict import is_forgery_flag
reload_profiles()

base = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
targets = []
for f in base.rglob("*.pdf"):
    nl = f.name.lower()
    if nl.startswith("квитанция (") or f.name.startswith("nvbr"):
        targets.append(f)

for f in sorted(targets):
    b = f.read_bytes()
    doc = fitz.open(stream=b, filetype="pdf")
    prod = doc.metadata.get("producer", "") or ""
    txt = "".join(p.get_text() for p in doc)
    doc.close()
    r = analyze(b, f.stem)
    d = r.get("details", {})
    hardflags = [x for x in r.get("flags", []) if is_forgery_flag(x)]
    print("====", ascii(str(f.relative_to(base))))
    print("   folder=", ascii(f.parent.name), "producer=", ascii(prod[:45]))
    print("   verdict=", r["verdict"], r["score"], "bank=", d.get("bank_key"), "chan=", d.get("channel"))
    # first meaningful text lines
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()][:6]
    print("   text:", ascii(" | ".join(lines)))
    for x in r.get("flags", []):
        print("      flag", ascii(x))
