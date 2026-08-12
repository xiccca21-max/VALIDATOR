import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.structure import content_stream_bytes

def dump(b: bytes, label: str) -> list[str]:
    cs = content_stream_bytes(b) or b""
    text = fitz.open(stream=b, filetype="pdf")[0].get_text()
    itogo_m = None
    for i, line in enumerate(text.splitlines()):
        if line.strip() == "Итого" and i + 1 < len(text.splitlines()):
            itogo_m = text.splitlines()[i + 1].strip()
            break
    lines = [f"=== {label} ===", f"itogo line: {itogo_m or '?'}"]
    # all Tj/TJ near amounts
    for m in re.finditer(rb"(\[[^\]]{0,200}\]|\([^)]{0,40}\))\s*TJ?", cs):
        chunk = m.group(1)
        if b"950" in chunk or b"500" in chunk or b"000" in chunk or b"5 0" in chunk:
            lines.append(f"  amt_chunk @{m.start()}: {chunk[:120]!r}")
    # hex strings length 4+
    hexes = re.findall(rb"<([0-9A-Fa-f]{4,})>", cs)
    lines.append(f"hex_strings={len(hexes)}")
    return lines

fake = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf").read_bytes()
orig = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии\ozonbank_document_20260131234821.pdf").read_bytes()
out = []
out.extend(dump(fake, "FAKE"))
out.extend(dump(orig, "ORIG 5000"))
Path(__file__).resolve().parents[1].joinpath("_ozon_cs_amount2.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")
