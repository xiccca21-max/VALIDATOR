"""Analyze _test10 batch PDFs vs bank originals."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.tbank import analyze
from detector.ff2_pool import extract_ff2_fingerprints, run_ff2_pool_check
from detector.glyf_fingerprint import run_glyf_checks, _pixel_hash_at_y

BATCH = [
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q01_55000_sber.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q02_82023_vtb.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q03_24780_psb.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q04_35000_alfa.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q05_100000_sber.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q06_25430_alfa.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q07_21000_digit1.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q08_90000_sber.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q09_15000_tbank.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test10\q10_12345_edge.pdf"),
]

SIZE_OK = (57_000, 61_000)


def image_info(path: Path) -> dict:
    doc = fitz.open(path)
    imgs = []
    for i in range(1, doc.xref_length()):
        o = doc.xref_object(i)
        if "Subtype /Image" not in o:
            continue
        w = re.search(r"/Width\s+(\d+)", o)
        h = re.search(r"/Height\s+(\d+)", o)
        cs = "Gray" if "DeviceGray" in o else "RGB"
        sm = "/SMask" in o
        imgs.append((cs, sm, int(w.group(1)) if w else 0, int(h.group(1)) if h else 0))
    helv = any("Helvetica" in f[3] for f in doc[0].get_fonts())
    doc.close()
    gray = sum(1 for x in imgs if x[0] == "Gray")
    smask = sum(1 for x in imgs if x[2])
    return {"n": len(imgs), "gray": gray, "smask_rgb": sum(1 for x in imgs if x[1]), "helv": helv}


def bank_span(path: Path) -> tuple[float | None, float | None]:
    doc = fitz.open(path)
    bank_right = None
    ruble_total = None
    for b in doc[0].get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                t = s["text"]
                if "банк" in t.lower() and "получат" in t.lower():
                    continue
                if bank_right is None and s["size"] == 9 and any(
                    x in t for x in ("Сбер", "Альф", "ВТБ", "Пром", "Т-Банк", "Ozon")
                ):
                    bank_right = round(s["bbox"][2], 1)
                if ruble_total is None and abs(s["origin"][1] - 106.61) < 0.5:
                    if "Rubl" in s.get("font", "") or (t.strip() == "i" and s["bbox"][0] > 230):
                        ruble_total = round(s["origin"][1], 2)
    doc.close()
    return bank_right, ruble_total


def main() -> None:
    print(f"{'file':22s} {'KB':>6s} {'xref':>4s} {'verdict':8s} {'score':>5s} {'img':>3s} {'bankR':>6s} {'rubY':>5s} {'ff2':>3s} {'glyf':>4s}")
    print("-" * 95)
    for p in BATCH:
        if not p.exists():
            print(f"{p.name:22s} MISSING")
            continue
        b = p.read_bytes()
        r = analyze(b, hashlib.md5(b).hexdigest())
        ff2 = run_ff2_pool_check(b)
        glyf = run_glyf_checks(b)
        doc = fitz.open(p)
        xref = doc.xref_length()
        doc.close()
        img = image_info(p)
        bank_r, rub_y = bank_span(p)
        sz_ok = SIZE_OK[0] <= len(b) <= SIZE_OK[1]
        print(
            f"{p.name:22s} {len(b)/1024:6.1f} {xref:4d} {r['verdict']:8s} {r['score']:5d} "
            f"{img['n']:3d} {str(bank_r or '-'):>6s} {str(rub_y or '-'):>5s} "
            f"{len(ff2.flags):3d} {len(glyf.flags):4d}"
            + ("" if sz_ok else " [SIZE]")
        )
        if r["flags"]:
            for f in r["flags"][:4]:
                print(f"  -> {f[:110]}")
        for f in ff2.flags[:2]:
            print(f"  ff2: {f.code} {f.detail[:80]}")
        for f in glyf.flags[:2]:
            print(f"  glyf: {f.code} {f.detail[:80]}")
        pix_t, _ = _pixel_hash_at_y(b, 106.61, "Итого")
        pix_0, _ = _pixel_hash_at_y(b, 203.22, "0")
        print(f"  glyf pix: Итого={pix_t}  0={pix_0}")
        ff = extract_ff2_fingerprints(b)
        if ff:
            print(f"  F1={ff['F1']['sha256_16']} F2={ff['F2']['sha256_16']} F3={ff['F3']['sha256_16']}")
        print()


if __name__ == "__main__":
    main()
