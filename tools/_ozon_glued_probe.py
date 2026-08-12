import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.structure import content_stream_bytes, find_streams, is_content_stream

def raw_lines(b):
    content = content_stream_bytes(b)
    if not content:
        for _, dec in find_streams(b):
            if dec and is_content_stream(dec):
                content = dec
                break
    return (content or b"").decode("latin1","replace").splitlines()

def glued_stats(lines):
    first_bt = next((i for i, ln in enumerate(lines) if re.search(r"\bBT\b", ln)), -1)
    pre = lines[:first_bt]
    glued = [ln for ln in pre if len(ln) > 500]
    # count lines with multiple operators (space-separated tokens ending with op)
    multi = 0
    for ln in pre:
        ops = re.findall(r"\b(cm|Tm|Td|TD|re|f|W|n|q|Q|rg|RG)\s*$", ln)
        if len(ops) > 1 or (len(ln) > 200 and " cm " in ln and " re " in ln):
            multi += 1
    nums = re.findall(r"(-?\d+\.\d+)", "\n".join(lines))
    bad_nums = [n for n in nums if re.search(r"\.\d*0{3,}$", n) or re.search(r"\.23999999", n)]
    return first_bt, len(pre), len(glued), multi, bad_nums[:5], pre[0][:80] if pre else ""

paths = [
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf",
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf",
]
corpus = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")
for p in sorted(corpus.glob("*.pdf")):
    paths.append(str(p))

for ps in paths[:35]:
    p = Path(ps)
    if not p.exists():
        continue
    b = p.read_bytes()
    lines = raw_lines(b)
    s = glued_stats(lines)
    tag = "FAKE" if "950000" in p.name or "20260713182949" in p.name else "orig"
    print(tag, p.name, s)
