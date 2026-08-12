import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import analyze

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
REC = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026.pdf")

fps = 0
for p in CORPUS.glob("*.pdf"):
    r = analyze(p.read_bytes())
    if r["verdict"] == "ФЕЙК":
        fps += 1
        print("FP", p.name, r["flags"][:2])
print(f"corpus FP: {fps}/128")

if REC.exists():
    r = analyze(REC.read_bytes())
    print(f"receipt: {r['verdict']}")
    for f in r["flags"][:8]:
        print(" ", f[:120])
