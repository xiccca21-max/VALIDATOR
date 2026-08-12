#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from detector.structure import find_streams, is_content_stream

CHEKI = Path.home() / "OneDrive" / "Desktop" / "чеки"

def inspect(bank, name):
    data = (CHEKI / bank / name).read_bytes()
    print(f"=== {bank}/{name} ===")
    print("text len", len(fitz.open(stream=data, filetype="pdf")[0].get_text()))
    for i, (raw, dec) in enumerate(find_streams(data)):
        if not dec:
            print(f"  s{i}: raw={len(raw)} FAIL decompress")
            continue
        ic = is_content_stream(dec)
        bt = b"BT" in dec
        tj = b"Tj" in dec or b"TJ" in dec
        tm = b"Tm" in dec
        print(f"  s{i}: raw={len(raw)} dec={len(dec)} content={ic} BT={bt} Tj={tj} Tm={tm}")
        if len(dec) < 20000:
            print("   head:", dec[:120])

for args in [
    ("уралсиб", "уралсиб сбп.pdf"),
    ("уралсиб", "уралсиб сбп4.pdf"),
    ("райф", "райф сбп2.pdf"),
    ("псб", "псб сбп 2.pdf"),
]:
    inspect(*args)
