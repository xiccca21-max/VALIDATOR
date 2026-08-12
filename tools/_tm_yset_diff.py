from pathlib import Path
import re, zlib, hashlib, fitz
from collections import Counter, defaultdict

INBOX=Path("output/defender_inbox")
GEN=Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
ALL=Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
gh={hashlib.sha256(p.read_bytes()).hexdigest() for p in ALL.rglob("*.pdf")}

def page_content(data):
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw=m.group(1)
        try: d=zlib.decompress(raw)
        except Exception:
            try: d=zlib.decompress(raw,-15)
            except Exception: continue
        if b"BT" in d and b"Tm" in d: return d
    return b""

def feats(data):
    c=page_content(data)
    if not c: return None
    height=None
    m=re.search(rb"/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s*\]", data)
    if m: height=float(m.group(1))
    tms=re.findall(rb"([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+Tm", c)
    yset=tuple(sorted({round(float(t[5]),1) for t in tms}))
    xset=tuple(sorted({round(float(t[4]),1) for t in tms}))
    return {
        "height": height, "clen": len(c),
        "bt": len(re.findall(rb"\bBT\b", c)),
        "tm": len(re.findall(rb"\sTm\b", c)),
        "yset": yset, "xset": xset,
        "yhash": hashlib.sha256(repr(yset).encode()).hexdigest()[:10],
        "xhash": hashlib.sha256(repr(xset).encode()).hexdigest()[:10],
    }

atlas=defaultdict(list)
for p in GEN.rglob("*.pdf"):
    d=p.read_bytes()
    if b"OpenPDF" not in d: continue
    f=feats(d)
    if f: atlas[f["height"]].append(f)

print("atlas heights", {h: len(v) for h,v in sorted(atlas.items())})
for h,fs in sorted(atlas.items()):
    print(" h", h, "yhashes", Counter(f["yhash"] for f in fs), "xhashes", Counter(f["xhash"] for f in fs))

# known novels from prior list
novels=[
"177075_seq_1785524520_02.pdf","177067_seq_1785524452_01.pdf","176827_seq_1785522584_01.pdf",
"176330_seq_1785518322_02.pdf","174732_seq_1785504515_03.pdf","174730_seq_1785504508_02.pdf",
"174724_seq_1785504483_02.pdf","174726_seq_1785504490_03.pdf","174891_seq_1785505880_02.pdf",
"176185_seq_1785516676_01.pdf","174873_seq_1785505717_02.pdf","174601_seq_1785503682_01.pdf",
"176271_seq_1785517430_03.pdf","176187_seq_1785516684_02.pdf","176189_seq_1785516698_03.pdf",
"176191_seq_1785516716_01.pdf","176193_seq_1785516729_02.pdf","176223_seq_1785516989_02.pdf",
"174889_seq_1785505870_01.pdf","174863_seq_1785505645_03.pdf","174855_seq_1785505608_02.pdf",
"174857_seq_1785505616_03.pdf","174853_seq_1785505600_01.pdf","174849_seq_1785505582_02.pdf",
"174847_seq_1785505574_01.pdf","174823_seq_1785505283_03.pdf","174821_seq_1785505276_02.pdf",
]
ym=xm=0
for n in novels:
    p=INBOX/n
    if not p.exists(): continue
    d=p.read_bytes()
    if hashlib.sha256(d).hexdigest() in gh: continue
    if b"OpenPDF" not in d: print(n, "not OpenPDF", len(d)); continue
    f=feats(d)
    gens=atlas.get(f["height"], [])
    y_ok=any(g["yset"]==f["yset"] for g in gens)
    x_ok=any(g["xset"]==f["xset"] for g in gens)
    ym += y_ok; xm += x_ok
    doc=fitz.open(stream=d, filetype="pdf")
    text=doc[0].get_text()
    sender="?"
    for i,ln in enumerate([x.strip() for x in text.splitlines() if x.strip()]):
        if ln=="Отправитель" and i>0: sender= [x.strip() for x in text.splitlines() if x.strip()][i-1]; break
    print(f"{n} h={f['height']} clen={f['clen']} bt={f['bt']} tm={f['tm']} y_ok={y_ok} x_ok={x_ok} yh={f['yhash']} xh={f['xhash']} sender={sender[:35]}")
print("y_ok_count", ym, "x_ok_count", xm, "of", len(novels))

# FP check: any genuine would fail y_ok?
print("genuine y self-match check:")
for h,fs in sorted(atlas.items()):
    # each should match at least itself in atlas
    fails=sum(1 for f in fs if not any(g["yset"]==f["yset"] for g in fs))
    print(" h", h, "self_fail", fails)
