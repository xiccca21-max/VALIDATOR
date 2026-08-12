"""Quick layout regression — verdict + layout tier only."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.tbank import analyze
from detector.tbank_text_layout_fingerprint import check_tbank_layout_fingerprint
from detector.reputation import file_hash
import fitz

ORIGINALS = [
    r"C:\Users\fanis\Downloads\Receipt (1).pdf",
    r"C:\Users\fanis\Downloads\Receipt (2).pdf",
]
CORPUS = r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк"

def check_path(path: str) -> tuple[str, str, int, int, int]:
    data = open(path, "rb").read()
    r = analyze(data, file_hash(data))
    d = fitz.open(stream=data, filetype="pdf")
    text = d[0].get_text()
    d.close()
    lf = check_tbank_layout_fingerprint(data, text)
    return (
        os.path.basename(path),
        r.get("verdict", "?"),
        len(lf.hard_flags),
        len(lf.supporting_flags),
        len([f for f in r.get("flags", []) if "LAYOUT" in str(f)]),
    )

failures = []
for p in ORIGINALS:
    if os.path.isfile(p):
        name, v, hard, sup, flags = check_path(p)
        print(f"ORIG {name}: verdict={v} layout_hard={hard} supporting={sup} verdict_flags={flags}")
        if v != "ЧИСТО":
            failures.append(name)

if os.path.isdir(CORPUS):
    n = fp = layout_hard_corpus = 0
    for fn in sorted(os.listdir(CORPUS)):
        if not fn.lower().endswith(".pdf"):
            continue
        path = os.path.join(CORPUS, fn)
        name, v, hard, sup, flags = check_path(path)
        n += 1
        if hard:
            layout_hard_corpus += 1
            if fp < 5:
                print(f"CORPUS HARD {name}: hard={hard} sup={sup}")
            fp += 1
        if v != "ЧИСТО" and flags:
            failures.append(f"corpus/{name}: {v} flags={flags}")
    print(f"CORPUS {n} pdf, layout_hard={layout_hard_corpus}, verdict_layout_fp={fp}")

if failures:
    print("FAIL", failures[:10])
    sys.exit(1)
print("STAGE2 PASS")
