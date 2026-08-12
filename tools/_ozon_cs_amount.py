import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.structure import content_stream_bytes

fake = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf").read_bytes()
corp_dir = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")

def cs_amount_info(b: bytes) -> dict:
    cs = content_stream_bytes(b) or b""
    text = fitz.open(stream=b, filetype="pdf")[0].get_text()
    itogo_m = re.search(r"Итого\s*\n\s*([^\n]+)", text)
    itogo = itogo_m.group(1).strip() if itogo_m else ""
    checks = {}
    for s in ["950000", "950 000", "950", "000", "5 000", "5000"]:
        checks[s] = s.encode() in cs
    # Tj strings with digits
    tj = re.findall(rb"\(([^()\\]{1,40})\)\s*Tj", cs)
    digit_tj = [t.decode("latin1", "replace") for t in tj if re.search(r"\d", t.decode("latin1", "replace"))]
    return {"itogo": itogo, "checks": checks, "digit_tj": digit_tj[:20], "cs_len": len(cs)}

lines = ["FAKE", str(cs_amount_info(fake))]
for p in sorted(corp_dir.glob("*.pdf"))[:3]:
    b = p.read_bytes()
    import fitz
    t = fitz.open(stream=b, filetype="pdf")[0].get_text()
    if "ID операции" in t:
        lines.append(p.name)
        lines.append(str(cs_amount_info(b)))

Path(__file__).resolve().parents[1].joinpath("_ozon_cs_amount.txt").write_text("\n".join(lines), encoding="utf-8")
print("done")
