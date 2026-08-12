import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.ozon import analyze as ozon_analyze
from detector.tbank import analyze as tbank_analyze
from detector.reputation import file_hash

FILES = [
    ("ozon", Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf")),
    ("ozon", Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf")),
    ("tbank", Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf")),
]

for bank, path in FILES:
    b = path.read_bytes()
    h = file_hash(b)
    fn = ozon_analyze if bank == "ozon" else tbank_analyze
    r = fn(b, h)
    print(path.name, "->", r.get("verdict"), r.get("flags", [])[:4])
