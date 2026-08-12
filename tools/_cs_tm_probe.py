from pathlib import Path
from collections import Counter
import re, zlib
from detector import route

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
INBOX = Path("output/defender_inbox")

def content_decoded_sizes(data: bytes) -> list[int]:
    out=[]
    for m in re.finditer(rb"stream\r?\n(.*?)\n?endstream", data, re.S):
        raw=m.group(1)
        try: dec=zlib.decompress(raw)
        except Exception: continue
        if b"BT" in dec or b"Tj" in dec or b"TJ" in dec:
            out.append(len(dec))
    return out

def tm_hi_prec(data: bytes) -> int:
    n=0
    for m in re.finditer(rb"stream\r?\n(.*?)\n?endstream", data, re.S):
        raw=m.group(1)
        try: dec=zlib.decompress(raw)
        except Exception: continue
        if b"Tm" not in dec: continue
        for t in re.findall(rb"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+Tm", dec):
            for x in t:
                if b"." in x and len(x.split(b".")[-1])>=3:
                    n+=1
        break
    return n

def max_content(data):
    xs=content_decoded_sizes(data)
    return max(xs) if xs else 0

g_sizes=[]; g_tm=Counter(); g_under=0
for p in CORPUS.rglob("*.pdf"):
    data=p.read_bytes(); cs=max_content(data); tm=tm_hi_prec(data)
    g_sizes.append(cs); g_tm[tm]+=1
    if cs and cs < 3000: g_under+=1
print("genuine content max_dec: min", min(g_sizes), "max", max(g_sizes), "med", sorted(g_sizes)[len(g_sizes)//2], "under3000", g_under, "n", len(g_sizes))
print("genuine tm_hi_prec", g_tm.most_common(8))

# CLEAN tbank seq
pdfs=sorted(INBOX.glob("*_seq_*.pdf"), key=lambda p:p.stat().st_mtime, reverse=True)
c_under=0; c_tm=0; c_n=0; c_sizes=[]
for p in pdfs[:150]:
    bank,res,_=route(p.read_bytes())
    if bank!="Т-Банк" or res.get("verdict")!="ЧИСТО": continue
    data=p.read_bytes(); cs=max_content(data); tm=tm_hi_prec(data)
    c_n+=1; c_sizes.append(cs)
    if cs and cs < 3000: c_under+=1
    if tm>0: c_tm+=1
print("clean n", c_n, "under3000", c_under, "tm_hi>0", c_tm, "cs min/max", min(c_sizes) if c_sizes else None, max(c_sizes) if c_sizes else None)

# Also check Новая папка genuines for under3000
NEW=Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\Новая папка")
nu=0; ns=[]
if NEW.exists():
  for p in NEW.rglob("*.pdf"):
    # only tbank-ish openpdf
    data=p.read_bytes()
    if b"OpenPDF" not in data and b"Jasper" not in data: continue
    cs=max_content(data); ns.append(cs)
    if cs and cs<3000: nu+=1
  print("newfolder openpdf under3000", nu, "n", len(ns), "min", min(ns) if ns else None)
