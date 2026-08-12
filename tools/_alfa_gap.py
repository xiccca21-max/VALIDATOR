from pathlib import Path
from collections import Counter, defaultdict
import re
from detector import route

INBOX = Path("output/defender_inbox")
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")

def meta(data: bytes):
    def grab(k):
        m = re.search(rf"/{k}\s*\(((?:[^()\\]|\\.)*)\)".encode(), data)
        return m.group(1).decode("latin1","replace") if m else ""
    return {
        "size": len(data),
        "Producer": grab("Producer")[:50],
        "Creator": grab("Creator")[:50],
        "nobj": len(re.findall(rb"\d+\s+0\s+obj", data)),
        "pdfver": (re.match(rb"%PDF-([\d.]+)", data).group(1).decode() if re.match(rb"%PDF-([\d.]+)", data) else ""),
    }

pdfs = sorted(INBOX.glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
clean=[]; fake=[]
for p in pdfs[:150]:
    bank,res,_=route(p.read_bytes())
    if "льфа" not in bank: continue
    if res.get("verdict")=="ЧИСТО": clean.append(p)
    elif res.get("verdict")=="ФЕЙК": fake.append((p, (res.get("flags") or [""])[0][:70]))

print("alfa_clean", len(clean), "alfa_fake", len(fake))
for p,f in fake[:8]:
    print("F", p.name, f)
print("--- CLEAN meta ---")
pc=Counter(); cc=Counter(); vc=Counter(); sc=[]
for p in clean[:30]:
    m=meta(p.read_bytes()); pc[m["Producer"]]+=1; cc[m["Creator"]]+=1; vc[m["pdfver"]]+=1; sc.append(m["size"])
    print("C", p.name, m["size"], m["Producer"], m["Creator"], m["nobj"], m["pdfver"])
print("prod", pc.most_common(5), "cre", cc.most_common(5), "ver", vc, "size", min(sc) if sc else None, max(sc) if sc else None)

print("--- GENUINE meta ---")
if CORPUS.exists():
    gp=Counter(); gc=Counter(); gv=Counter(); gs=[]
    for p in list(CORPUS.rglob("*.pdf"))[:80]:
        m=meta(p.read_bytes()); gp[m["Producer"]]+=1; gc[m["Creator"]]+=1; gv[m["pdfver"]]+=1; gs.append(m["size"])
    print("genuine_n", len(gs), "prod", gp.most_common(5), "cre", gc.most_common(5), "ver", dict(gv), "size", min(gs), max(gs), sorted(gs)[len(gs)//2])
else:
    print("no_corpus", CORPUS)
