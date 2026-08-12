from pathlib import Path
from collections import Counter, defaultdict
import json, re, zlib, hashlib
from detector import route
from detector.tbank_v6.engine import analyze as tbank_analyze
from detector.ff2_pool import _extract_fontfile2
from detector.tbank_v6.known_signatures import _table_sha256

INBOX = Path("output/defender_inbox")
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")

pdfs = sorted(INBOX.glob("*_seq_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
clean = []
for p in pdfs[:120]:
    bank, res, _ = route(p.read_bytes())
    if bank == "Т-Банк" and res.get("verdict") == "ЧИСТО":
        clean.append(p)
print("clean_tbank", len(clean))

# Full v6 details on first 12 CLEAN
soft = Counter()
ignored = Counter()
for p in clean[:12]:
    r = tbank_analyze(p.read_bytes())
    d = r.get("details") or {}
    print("---", p.name, "size", p.stat().st_size, "score", r.get("score"))
    print("  subtype", d.get("receipt_subtype"), d.get("channel"), "hard", d.get("hard_count"), "sup", d.get("supporting_count"))
    for f in (r.get("flags") or []):
        print("  FLAG", f[:100])
    for obs in (d.get("ignored_observations") or [])[:8]:
        ignored[str(obs)[:60]] += 1
        print("  ign", str(obs)[:120])
    # expert supporting lines
    er = d.get("expert_report") or {}
    for ln in (er.get("body_lines") or [])[:15]:
        if any(k in ln.upper() for k in ("SUPPORT", "B1", "B2", "DIAG", "MISMATCH", "EDIT", "REBUILD", "SIZE", "FONT")):
            print("  exp", ln[:140])
            soft[ln[:50]] += 1

print("ignored_top", ignored.most_common(12))

# Structural byte features: CLEAN vs genuine
def feats(data: bytes):
    kw = ""
    m = re.search(rb"/Keywords\s*\(((?:[^()\\]|\\.)*)\)", data)
    if m: kw = m.group(1).decode("latin1","replace")
    tail = kw.split("|")[-1].strip() if "|" in kw else ""
    # content stream edits markers
    n_pct = data.count(b"%")
    # whitespace padding after ET
    et_pad = len(re.findall(rb"ET\s{3,}", data))
    # FontBBox count
    n_bbox = len(re.findall(rb"/FontBBox", data))
    ttf = _extract_fontfile2(data, "F2")
    pack = None
    if ttf:
        pack = (_table_sha256(ttf, b"glyf")[:12], _table_sha256(ttf, b"loca")[:12])
    # /W pretty?
    pretty_w = bool(re.search(rb"/W\s*\[\s*\n", data))
    return {"size": len(data), "kw_tail": tail, "et_pad": et_pad, "n_bbox": n_bbox, "pack": pack, "pretty_w": pretty_w, "nobj": len(re.findall(rb"\d+\s+0\s+obj", data))}

print("=== feature compare ===")
cg = Counter(); cc = Counter()
for p in list(CORPUS.rglob("*.pdf"))[:80]:
    f = feats(p.read_bytes()); cg[f"tail:{f['kw_tail']}"]+=1; cg[f"et:{f['et_pad']}"]+=1; cg[f"obj:{f['nobj']}"]+=1; cg[f"pw:{f['pretty_w']}"]+=1
for p in clean[:30]:
    f = feats(p.read_bytes()); cc[f"tail:{f['kw_tail']}"]+=1; cc[f"et:{f['et_pad']}"]+=1; cc[f"obj:{f['nobj']}"]+=1; cc[f"pw:{f['pretty_w']}"]+=1
    print("C", p.name, f)
print("genuine", cg.most_common(15))
print("clean", cc.most_common(15))
