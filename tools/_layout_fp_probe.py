import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.tbank import analyze
from detector.tbank_text_layout_fingerprint import check_tbank_layout_fingerprint
from detector.reputation import file_hash

def check(path: Path) -> dict:
    b = path.read_bytes()
    d = fitz.open(stream=b, filetype="pdf")
    text = d[0].get_text()
    d.close()
    layout = check_tbank_layout_fingerprint(b, text, shadow=False, regression_passed=True)
    r = analyze(b, file_hash(b))
    return {
        "name": path.name,
        "verdict": r.get("verdict"),
        "hard_layout": layout.hard_flags,
        "lines": [(ln.text, ln.font, ln.end_x, ln.deviation) for ln in layout.lines if ln.deviation > 1 or ln.end_x > 250],
    }

targets = [
    Path(r"C:\Users\fanis\Downloads\Receipt (1).pdf"),
    Path(r"C:\Users\fanis\Downloads\Receipt (2).pdf"),
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf"),
]
corpus = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")

lines = ["=== TARGETS ==="]
for p in targets:
    if p.exists():
        info = check(p)
        lines.append(str(info))

lines.append("\n=== CORPUS layout hard flags ===")
fp = 0
for p in sorted(corpus.glob("*.pdf")):
    b = p.read_bytes()
    d = fitz.open(stream=b, filetype="pdf")
    text = d[0].get_text()
    d.close()
    layout = check_tbank_layout_fingerprint(b, text, shadow=False, regression_passed=True)
    if layout.hard_flags:
        fp += 1
        lines.append(f"FP {p.name}: {layout.hard_flags[:2]}")
lines.append(f"corpus hard count: {fp}/{len(list(corpus.glob('*.pdf')))}")

out = Path(__file__).resolve().parents[1] / "_layout_fp_probe.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("written", out, "corpus_fp", fp)
