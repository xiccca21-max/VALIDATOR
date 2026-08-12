import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.ozon_profiles import extract_sbp_opid

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии")
FAKE = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf")

AMOUNT_RE = re.compile(r"^((?:0|[1-9]\d{0,2}(?: \d{3})*)(?:,\d{2})?)\s*₽$")

def amounts(text: str) -> list[str]:
    out = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() in ("Итого", "Сумма") and i + 1 < len(lines):
            out.append(lines[i + 1].strip())
    return out

def valid_amount(s: str) -> bool:
    return bool(AMOUNT_RE.fullmatch(s.strip()))

lines = []
for p in sorted(CORPUS.glob("*.pdf")):
    t = fitz.open(stream=p.read_bytes(), filetype="pdf")[0].get_text()
    opid = extract_sbp_opid(t) or ""
    ams = amounts(t)
    bad = [a for a in ams if not valid_amount(a)]
    if opid:
        lines.append(f"{p.name} tail={opid[11:]} valid={not bad} bad={bad}")

if FAKE.exists():
    t = fitz.open(stream=FAKE.read_bytes(), filetype="pdf")[0].get_text()
    opid = extract_sbp_opid(t) or ""
    ams = amounts(t)
    lines.append(f"FAKE tail={opid[11:]} amounts={ams} valid={[valid_amount(a) for a in ams]}")

Path(__file__).resolve().parents[1].joinpath("_ozon_tail_amount.txt").write_text("\n".join(lines), encoding="utf-8")
print("lines", len(lines))
