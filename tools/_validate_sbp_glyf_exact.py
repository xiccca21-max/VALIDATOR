"""Validate TBANK_SBP_F1_GLYF_CMAP_UNKNOWN: 0 FP genuines, catch SEQ CLEAN/FAIL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank_v6 import analyze  # noqa: E402
from detector.tbank_v6.f1_subset_shape import check_f1_subset_shape  # noqa: E402

CODE = "TBANK_SBP_F1_GLYF_CMAP_UNKNOWN"


def hard_codes(r: dict) -> list[str]:
    out = []
    for f in r.get("flags") or []:
        if isinstance(f, str) and f.startswith("["):
            out.append(f[1 : f.index("]")])
    return out


def main() -> None:
    genu_root = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
    fp = 0
    n = 0
    for p in genu_root.rglob("*.pdf"):
        data = p.read_bytes()
        if b"OpenPDF" not in data:
            continue
        if b"270 519" not in data and b"[0 0 270 519]" not in data:
            continue
        n += 1
        flags = [f.code for f in check_f1_subset_shape(data).flags]
        if CODE in flags:
            fp += 1
            print("FP", p, flags)
    print(f"genuines h=519 OpenPDF: {n}, FP on {CODE}: {fp}")

    inbox = Path("output/defender_inbox")
    caught = 0
    still = 0
    for p in sorted(inbox.glob("*_seq_*.pdf")):
        data = p.read_bytes()
        if b"270 519" not in data and b"[0 0 270 519]" not in data:
            continue
        try:
            mid = int(p.name.split("_", 1)[0])
        except ValueError:
            continue
        if mid < 180980:
            continue
        r = analyze(data, file_hash=p.stem)
        codes = hard_codes(r)
        if r.get("verdict") == "ЧИСТО":
            still += 1
            print("STILL_CLEAN", p.name, codes)
        elif CODE in codes:
            caught += 1
    print(f"recent SBP seq: caught_via_new={caught}, still_clean={still}")

    for name in (
        "180985_seq_1785701969_01.pdf",
        "180987_seq_1785701978_02.pdf",
        "180878_seq_1785700332_04.pdf",  # card PASS at competitor — must NOT get SBP rule
    ):
        p = inbox / name
        data = p.read_bytes()
        flags = [f.code for f in check_f1_subset_shape(data).flags]
        r = analyze(data, file_hash=p.stem)
        print(name, "shape_flags", flags, "verdict", r.get("verdict"), hard_codes(r)[:4])

    receipt = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt_02.08.2026 (16).pdf")
    if receipt.exists():
        flags = [f.code for f in check_f1_subset_shape(receipt.read_bytes()).flags]
        print("receipt_16", flags)


if __name__ == "__main__":
    main()
