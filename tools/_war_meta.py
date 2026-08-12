from pathlib import Path
from collections import Counter
import re
from detector import route

inbox = Path("output/defender_inbox")
genuine = Path("чеки/т банк")
if not genuine.exists():
    genuine = Path("чеки/тбанк")
print("genuine_dir", genuine, genuine.exists())

def meta(data: bytes):
    size = len(data)
    prod = ""
    m = re.search(rb"/Producer\s*\(([^)]{0,80})\)", data)
    if m: prod = m.group(1).decode("latin1","replace")
    m2 = re.search(rb"/Creator\s*\(([^)]{0,80})\)", data)
    cre = m2.group(1).decode("latin1","replace") if m2 else ""
    n_ff2 = len(re.findall(rb"/FontFile2\s+\d+\s+\d+\s+R", data))
    n_obj = data.count(b" endobj")
    has_java = b"Java" in data or b"iText" in data or b"OpenPDF" in data
    return size, prod[:40], cre[:40], n_ff2, n_obj, has_java

pdfs = sorted(inbox.glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
clean_tb=[]; fake_tb=[]
for p in pdfs[:80]:
    bank,res,_=route(p.read_bytes())
    if bank!="Т-Банк": continue
    if res.get("verdict")=="ЧИСТО": clean_tb.append(p)
    elif res.get("verdict")=="ФЕЙК": fake_tb.append(p)

print("clean_tb", len(clean_tb), "fake_tb", len(fake_tb))
print("--- CLEAN sizes ---")
for p in clean_tb[:12]:
    print(p.name, *meta(p.read_bytes()))
print("--- FAKE sizes ---")
for p in fake_tb[:8]:
    print(p.name, *meta(p.read_bytes()), (res:=route(p.read_bytes())[1]).get("flags",[])[:1])

gens = list(genuine.rglob("*.pdf"))[:40] if genuine.exists() else []
print("genuine_sample", len(gens))
if gens:
    sizes=[meta(p.read_bytes())[0] for p in gens]
    print("genuine_size_min_max_med", min(sizes), max(sizes), sorted(sizes)[len(sizes)//2])
    prods=Counter(meta(p.read_bytes())[1] for p in gens)
    print("genuine_prods", prods.most_common(5))
    cre=Counter(meta(p.read_bytes())[2] for p in gens)
    print("genuine_cre", cre.most_common(5))
