import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from detector.structure import content_stream_bytes, find_streams, is_content_stream

def inspect(path: Path) -> dict:
    b = path.read_bytes()
    content = content_stream_bytes(b)
    if not content:
        for _, dec in find_streams(b):
            if dec and is_content_stream(dec):
                content = dec
                break
    lines = content.decode("latin1", "replace").splitlines() if content else []
    first_bt = next((i for i, ln in enumerate(lines) if ln.strip() == "BT" or ln.strip().endswith(" BT")), -1)
    pre_bt = lines[:first_bt] if first_bt > 0 else []
    pre_joined = b"\n".join(ln.encode() for ln in pre_bt)
    glued = len(pre_bt) == 1 and len(pre_bt[0]) > 200
    nums = re.findall(r"(-?\d+\.\d+)", content.decode("latin1", "replace")[:4000] if content else "")
    trailing_zeros = [n for n in nums if re.search(r"\.\d*0{2,}$", n)]
    d = fitz.open(stream=b, filetype="pdf")
    meta = d.metadata or {}
    d.close()
    head = b[:8000]
    ver = "1.4" if b"%PDF-1.4" in head[:16] else "?"
    xref_style = "classic" if b"xref\n0 " in b[:50000] or b"xref\r\n0 " in b[:50000] else "other"
    return {
        "path": path.name,
        "producer": meta.get("producer", ""),
        "lines_total": len(lines),
        "pre_bt_lines": len(pre_bt),
        "pre_bt_glued_one_line": glued,
        "first_bt_idx": first_bt,
        "pre_bt_sample": (pre_bt[0][:300] if pre_bt else "")[:300],
        "line_after_pre": lines[first_bt:first_bt + 5] if first_bt >= 0 else [],
        "trailing_zero_nums": trailing_zeros[:12],
        "pdf_ver": ver,
        "xref_style": xref_style,
        "m105": "m105" in (meta.get("producer") or "").lower(),
    }

fake = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf")
corpus = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")

out = []
out.append("FAKE:")
out.append(str(inspect(fake)))
for p in sorted(corpus.glob("*.pdf"))[:5]:
    out.append("ORIG " + str(inspect(p)))

text = "\n".join(str(x) for x in out)
Path(__file__).resolve().parents[1].joinpath("_ozon_serializer_probe.txt").write_text(text, encoding="utf-8")
print(text)
