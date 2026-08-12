import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.structure import content_stream_bytes

def analyze(path: Path):
    b = path.read_bytes()
    content = content_stream_bytes(b) or b""
    text = content.decode("latin1", "replace")
    lines = text.splitlines()
    first_bt = next((i for i, ln in enumerate(lines) if re.search(r"\bBT\b", ln)), -1)
    pre = lines[:first_bt] if first_bt > 0 else []
    # glued: many ops on single physical line
    long_lines = [(i, len(ln), ln[:120]) for i, ln in enumerate(pre) if len(ln) > 400]
    # numeric trailing zeros in pre section
    nums = re.findall(r"(-?\d+\.\d+)", "\n".join(pre))
    tz = [n for n in nums if re.search(r"0{2,}$", n.split(".")[-1]) and len(n) > 4]
    # newline density pre-BT
    ops = len(re.findall(r"\b(cm|Tm|Td|TD|q|Q|re|f|W|n)\b", "\n".join(pre)))
    return {
        "name": path.name,
        "pre_lines": len(pre),
        "pre_long_lines": long_lines[:3],
        "ops_pre_bt": ops,
        "trailing_zero_nums": sorted(set(tz))[:8],
        "first3_pre": pre[:3],
        "last3_pre": pre[-3:],
        "post_bt_5": lines[first_bt:first_bt+5],
    }

paths = [
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf"),
]
corpus = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")
paths += sorted(corpus.glob("*.pdf"))[:8]

for p in paths:
    print("---", analyze(p))
