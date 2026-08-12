import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.structure import content_skeleton_hash, content_stream_bytes
from detector.ozon_profiles import check_total_arithmetic, classify_family, extract_sbp_opid

FAKE = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf")
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")

def inspect(path: Path) -> dict:
    b = path.read_bytes()
    doc = fitz.open(stream=b, filetype="pdf")
    text = doc[0].get_text()
    doc.close()
    cs = content_stream_bytes(b) or b""
    amounts = re.findall(r"Итого\s*\n\s*([^\n]+)", text)
    sums = re.findall(r"Сумма\s*\n\s*([^\n]+)", text)
    arith = check_total_arithmetic(text)
    return {
        "name": path.name,
        "size": len(b),
        "skeleton": content_skeleton_hash(b),
        "cs_len": len(cs),
        "family": classify_family(text),
        "amounts_itogo": amounts,
        "amounts_summa": sums,
        "arith": arith,
        "opid": extract_sbp_opid(text),
        "pad_comments": sum(1 for ln in cs.split(b"\n") if ln.strip().startswith(b"%") and len(ln.strip()) > 12),
        "has_950": b"950000" in cs,
        "sender_recv_same": "Отправитель" in text and text.count("Максим") >= 2,
    }

lines = ["=== FAKE ===", str(inspect(FAKE))]
if CORPUS.exists():
    sbp = []
    for p in sorted(CORPUS.glob("*.pdf")):
        d = inspect(p)
        if d["family"] == "SBP_OUT":
            sbp.append(d)
    lines.append(f"=== CORPUS SBP_OUT {len(sbp)} ===")
    for d in sbp[:5]:
        lines.append(str({k: d[k] for k in ["name","amounts_itogo","amounts_summa","arith","cs_len","pad_comments"]}))
    # amount format patterns
    patterns = set()
    for d in sbp:
        for a in d["amounts_itogo"] + d["amounts_summa"]:
            patterns.add(re.sub(r"\d", "N", a.strip()))
    lines.append("amount_patterns=" + str(sorted(patterns)[:20]))

out = Path(__file__).resolve().parents[1] / "_ozon_fake_compare.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("ok", out)
