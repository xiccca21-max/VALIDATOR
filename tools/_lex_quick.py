import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import analyze
from detector.tbank_info_keywords_lex import check_info_keywords_lex

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
REC = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026.pdf")

fps = sum(1 for p in CORPUS.glob("*.pdf") if check_info_keywords_lex(p.read_bytes()).mismatch)
print(f"corpus FP: {fps}/128")

r = check_info_keywords_lex(REC.read_bytes())
print(f"receipt: mismatch={r.mismatch} stats={r.stats}")
print(f"verdict: {analyze(REC.read_bytes())['verdict']}")
