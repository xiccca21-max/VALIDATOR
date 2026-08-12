from pathlib import Path
from collections import Counter
import re
from detector import route

inbox = Path("output/defender_inbox")
genuine_dirs = [Path("чеки/т банк"), Path("чеки/тбанк"), Path("чеки/T-Bank")]
genuine = next((d for d in genuine_dirs if d.exists()), None)
print("genuine_dir", genuine)

def meta(data: bytes):
    size = len(data)
    prod = ""
    m = re.search(rb"/Producer\s*\(([^)]{0,120})\)", data)
    if m: prod = m.group(1).decode("latin1","replace")
    m2 = re.search(rb"/Creator\s*\(([^)]{0,120})\)", data)
    cre = m2.group(1).decode("latin1","replace") if m2 else ""
    n_ff2 = len(re.findall(rb"/FontFile2\s+\d+\s+\d+\s+R", data))
    xref = b"/XRef" in data or b" startxref" in data
    # content whitespace density
    streams = re.findall(rb"stream\r?\n(.*?)\n?endstream", data, re.S)
    ws = sum(s.count(b" ") + s.count(b"\n") for s in streams[:5])
    return {"size": size, "prod": prod[:50], "cre": cre[:50], "ff2": n_ff2, "ws": ws, "nstream": len(streams)}

pdfs = sorted(inbox.glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
clean_tb=[]; fake_tb=[]; clean_alfa=[]
for p in pdfs[:100]:
    bank,res,_=route(p.read_bytes())
    v=res.get("verdict")
    if bank=="Т-Банк" and v=="ЧИСТО": clean_tb.append(p)
    elif bank=="Т-Банк" and v=="ФЕЙК": fake_tb.append(p)
    elif bank=="Альфа-Банк" and v=="ЧИСТО": clean_alfa.append(p)

print("counts", len(clean_tb), len(fake_tb), len(clean_alfa))
prods_c=Counter(); sizes_c=[]
for p in clean_tb[:25]:
    m=meta(p.read_bytes()); prods_c[m["prod"]]+=1; sizes_c.append(m["size"])
    print("C", p.name, m["size"], m["prod"], m["cre"], m["ff2"], m["ws"])
print("clean_prod", prods_c.most_common(5), "size", min(sizes_c) if sizes_c else None, max(sizes_c) if sizes_c else None)

if genuine:
    gens=list(genuine.rglob("*.pdf"))[:80]
    prods_g=Counter(); sizes_g=[]; cre_g=Counter()
    for p in gens:
        m=meta(p.read_bytes()); prods_g[m["prod"]]+=1; cre_g[m["cre"]]+=1; sizes_g.append(m["size"])
    print("genuine_n", len(gens), "size", min(sizes_g), max(sizes_g), sorted(sizes_g)[len(sizes_g)//2])
    print("genuine_prod", prods_g.most_common(6))
    print("genuine_cre", cre_g.most_common(6))
