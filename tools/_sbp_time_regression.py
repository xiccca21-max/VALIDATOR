"""Fast SBP timestamp regression — no full analyze/Java."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from detector.sbp_cipher import extract_sbp_opid
from detector.tbank_sbp_content import validate_tbank_sbp_id

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
FIXED = Path(r"C:\Users\fanis\Downloads\Receipt (2).pdf")

sbp_total = ts_hits = 0
for p in sorted(CORPUS.glob("*.pdf")):
    b = p.read_bytes()
    try:
        text = fitz.open(stream=b, filetype="pdf")[0].get_text()
    except Exception:
        continue
    opid = extract_sbp_opid(text)
    if not opid:
        continue
    sbp_total += 1
    r = validate_tbank_sbp_id(opid, text, b)
    ts = [f for f in r.flags if f.code == "SBP_CIPHER_TIMESTAMP"]
    if ts:
        ts_hits += 1
        print(f"FP {p.name}: {ts[0].detail}")

print(f"corpus SBP: {sbp_total}, TIMESTAMP hits: {ts_hits}")

if FIXED.exists():
    b = FIXED.read_bytes()
    text = fitz.open(stream=b, filetype="pdf")[0].get_text()
    opid = extract_sbp_opid(text)
    r = validate_tbank_sbp_id(opid, text, b)
    ts = [f for f in r.flags if f.code == "SBP_CIPHER_TIMESTAMP"]
    print(f"Receipt (2): timestamp_flags={len(ts)} all_flags={[f.code for f in r.flags]}")
