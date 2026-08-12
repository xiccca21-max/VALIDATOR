from pathlib import Path
from collections import Counter
from detector import route

inbox = Path("output/defender_inbox")
pdfs = sorted(inbox.glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
c = Counter(); banks = Counter(); clean_paths = []
for p in pdfs[:120]:
    bank, res, _ = route(p.read_bytes())
    v = res.get("verdict")
    c[v] += 1
    banks[f"{bank}|{v}"] += 1
    if v == "ЧИСТО":
        clean_paths.append((bank, p))
print("last120_seq", dict(c))
for k,v in sorted(banks.items(), key=lambda x:-x[1]):
    print(k, v)
print("CLEAN_PATHS")
for bank,p in clean_paths[:25]:
    print(f"{bank}\t{p}")
