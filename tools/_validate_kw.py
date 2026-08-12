from pathlib import Path
from collections import Counter
from detector import route

# FP: genuines
fp = Counter()
for root in [Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк"), Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\Новая папка")]:
    for p in root.rglob("*.pdf"):
        bank, res, _ = route(p.read_bytes())
        if bank != "Т-Банк":
            continue
        v = res.get("verdict")
        fp[v] += 1
        if v == "ФЕЙК":
            print("FP", p, (res.get("flags") or [])[:2])
print("genuine_tbank_verdicts", dict(fp))

# Catch: recent SEQ
c = Counter(); codes = Counter(); banks = Counter()
pdfs = sorted(Path("output/defender_inbox").glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
for p in pdfs[:120]:
    bank, res, _ = route(p.read_bytes())
    v = res.get("verdict")
    c[v] += 1
    banks[f"{bank}|{v}"] += 1
    for f in (res.get("flags") or [])[:2]:
        code = f.split("]")[0].lstrip("[") if f.startswith("[") else f[:40]
        codes[code] += 1
print("last120_seq", dict(c))
for k,v in sorted(banks.items(), key=lambda x:-x[1]):
    print(" ", k, v)
print("top_codes", codes.most_common(8))
