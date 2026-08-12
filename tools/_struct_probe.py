from pathlib import Path
from collections import Counter
from detector.ff2_pool import _extract_fontfile2
from detector.tbank_v6.known_signatures import _table_sha256
from detector.defender_pins import load_tbank_extra_packs
from detector.tbank_v6.rules import K_FONT_002_PACKS
from detector.tbank_v6.genuine_f2_packs import GENUINE_F2_PACKS
from detector import route
import re

extras = load_tbank_extra_packs()
known = set(K_FONT_002_PACKS) | extras
print("known_total", len(known), "extras", len(extras), "overlap_genuine", len(known & GENUINE_F2_PACKS))

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
# Fast: only F2 pack match on genuines
hits=[]
for p in CORPUS.rglob("*.pdf"):
    ttf=_extract_fontfile2(p.read_bytes(),"F2")
    if not ttf: continue
    g=_table_sha256(ttf,b"glyf"); l=_table_sha256(ttf,b"loca")
    if (g,l) in known:
        hits.append((p.name,g[:12],l[:12]))
print("genuine_kfont_hits", len(hits))
for h in hits[:10]: print(" FP", h)

# Structural: Keywords tail / Info lex on CLEAN vs genuines
from detector.tbank_keywords_generation import check_keywords_generation
from detector.tbank_info_keywords_lex import check_info_keywords_lex

def kw_tail(data):
    m=re.search(rb"/Keywords\s*\((?:[^)\\]|\\.)*\|([0-9A-Fa-f]{32})\|(\d+)\)", data)
    if not m:
        m=re.search(rb"/Keywords\s*\(((?:[^()\\]|\\.)*)\)", data)
        return ("raw", (m.group(1).decode("latin1","replace")[-20:] if m else None))
    return m.group(2).decode(), m.group(1).decode()[:8]

INBOX=Path("output/defender_inbox")
pdfs=sorted(INBOX.glob("*_seq_*.pdf"), key=lambda p:p.stat().st_mtime, reverse=True)
clean=[]
for p in pdfs[:100]:
    bank,res,_=route(p.read_bytes())
    if bank=="Т-Банк" and res.get("verdict")=="ЧИСТО":
        clean.append(p)

print("clean", len(clean))
tails_c=Counter(); tails_g=Counter()
for p in clean[:20]:
    t=kw_tail(p.read_bytes()); tails_c[t[0] if isinstance(t,tuple) else t]+=1
    # run keyword checks
    try:
        r1=check_keywords_generation(p.read_bytes())
        print("kwgen", p.name, getattr(r1,"flags",r1))
    except Exception as e:
        print("kwgen_err", type(e).__name__, e)
for p in list(CORPUS.rglob("*.pdf"))[:40]:
    t=kw_tail(p.read_bytes()); tails_g[str(t[0])]+=1
print("tails_clean", tails_c)
print("tails_genuine_sample", tails_g)
