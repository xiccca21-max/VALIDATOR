from pathlib import Path
from collections import Counter
from detector import route

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
INBOX = Path("output/defender_inbox")

gens = list(CORPUS.rglob("*.pdf"))
print("genuine_n", len(gens))
verdicts=Counter(); kfont=0; fakes=[]
for p in gens:
    bank, res, _ = route(p.read_bytes())
    v=res.get("verdict")
    verdicts[v]+=1
    flags="|".join(res.get("flags") or [])
    if "K-FONT-002" in flags:
        kfont+=1
        if len(fakes)<8: fakes.append((p.name, v, flags[:140]))
print("verdicts", dict(verdicts), "kfont002", kfont)
for row in fakes: print(" ", row)

# CLEAN SEQ supporting flags?
pdfs=sorted(INBOX.glob("*_seq_*.pdf"), key=lambda p:p.stat().st_mtime, reverse=True)
soft=Counter(); n=0
for p in pdfs[:150]:
    bank,res,_=route(p.read_bytes())
    if bank!="Т-Банк" or res.get("verdict")!="ЧИСТО": continue
    n+=1
    for f in res.get("flags") or []:
        soft[f.split("]")[0].lstrip("[") if f.startswith("[") else f[:40]]+=1
    # also details
    d=res.get("details") or {}
    if n<=3:
        print("clean_sample", p.name, "flags", res.get("flags"), "score", res.get("score"))
print("clean_n", n, "soft_flags", soft.most_common(15))
