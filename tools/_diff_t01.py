"""Visual + forensic diff: t01 fake vs Receipt originals."""
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

FAKE = Path(
    r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test5_jasper\t01_55000_Сбер.pdf"
)
ORIGS = [
    Path(r"c:\Users\fanis\Downloads\Receipt (16).pdf"),
    Path(r"c:\Users\fanis\Downloads\Receipt (14).pdf"),
    Path(r"c:\Users\fanis\Downloads\Receipt (5).pdf"),
    Path(r"c:\Users\fanis\Downloads\Receipt (23).pdf"),
    Path(r"c:\Users\fanis\Downloads\Receipt (18).pdf"),
]


def spans_detail(path: Path) -> list[dict]:
    doc = fitz.open(path)
    page = doc[0]
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for sp in line["spans"]:
                text = sp["text"].strip()
                if not text:
                    continue
                bbox = sp["bbox"]
                out.append({
                    "text": text[:40],
                    "font": sp["font"],
                    "size": round(sp["size"], 2),
                    "flags": sp["flags"],
                    "origin": (round(sp["origin"][0], 2), round(sp["origin"][1], 2)),
                    "bbox": tuple(round(x, 2) for x in bbox),
                    "w": round(bbox[2] - bbox[0], 2),
                    "h": round(bbox[3] - bbox[1], 2),
                    "right": round(bbox[2], 2),
                })
    doc.close()
    return out


def find_label(spans: list[dict], label: str) -> dict | None:
    for i, s in enumerate(spans):
        if s["text"] == label:
            if i + 1 < len(spans):
                return spans[i + 1]
            break
    return None


def find_by_y(spans: list[dict], y: float, tol: float = 0.8) -> list[dict]:
    return [s for s in spans if abs(s["origin"][1] - y) < tol]


def meta(path: Path) -> dict:
    doc = fitz.open(path)
    m = doc.metadata or {}
    doc.close()
    return {
        "producer": m.get("producer", ""),
        "creator": m.get("creator", ""),
        "keywords": m.get("keywords", ""),
        "creation": m.get("creationDate", ""),
    }


def report_file(path: Path, label: str) -> None:
    b = path.read_bytes()
    r = analyze(b, hashlib.md5(b).hexdigest())
    sp = spans_detail(path)
    print(f"\n{'='*70}\n{label}: {path.name}\nverdict={r['verdict']} score={r['score']}")
    if r["flags"]:
        for f in r["flags"][:6]:
            print(f"  FLAG: {f[:100]}")

    ff2 = extract_ff2_fingerprints(b)
    if ff2:
        print(f"  FF2: F1={ff2['F1']['sha256_16']}({ff2['F1']['size']}B) "
              f"F2={ff2['F2']['sha256_16']}({ff2['F2']['size']}B) "
              f"F3={ff2['F3']['sha256_16']}({ff2['F3']['size']}B)")

    # key layout rows
    rows = {
        "date": find_by_y(sp, 86.46),
        "total": find_by_y(sp, 106.61),
        "bank": find_label(sp, "Банк получателя") or find_label(sp, "Банк"),
        "sbp_main": None,
        "commission": find_by_y(sp, 203.22),
        "account": find_by_y(sp, 331.22),
    }
    for s in sp:
        if s["text"].startswith("B6") or s["text"].startswith("A6"):
            if len(s["text"]) >= 20:
                rows["sbp_main"] = s
                break

    print("  --- layout ---")
    for k in ("date", "total", "bank", "sbp_main", "commission", "account"):
        v = rows[k]
        if isinstance(v, list):
            for s in v:
                print(f"  {k}: {s['text']!r} font={s['font'][-20:]} size={s['size']} "
                      f"origin={s['origin']} right={s['right']} h={s['h']}")
        elif v:
            print(f"  {k}: {v['text']!r} font={v['font'][-20:]} size={v['size']} "
                  f"origin={v['origin']} right={v['right']} h={v['h']}")

    pix0, _ = _pixel_hash_at_y(b, 203.22, "0")
    pix_t, _ = _pixel_hash_at_y(b, 106.61, "Итого")
    print(f"  glyf pix: Итого={pix_t}  commission_0={pix0}")


def compare_bank_alignment():
    print("\n" + "=" * 70)
    print("BANK ROW ALIGNMENT (value after label)")
    for path in [FAKE] + ORIGS:
        sp = spans_detail(path)
        bank = None
        for i, s in enumerate(sp):
            if "Банк" in s["text"] and "получател" in s["text"].lower():
                # value is usually previous span in fitz order for this template
                pass
        for i, s in enumerate(sp):
            if s["text"] in ("Сбербанк", "Альфа-Банк", "ВТБ", "Промсвязьбанк", "Т-Банк", "Газпромбанк"):
                bank = s
                break
        if bank:
            print(f"  {path.name:22s} bank={bank['text']!r:16s} origin_x={bank['origin'][0]:7.2f} "
                  f"right={bank['right']:7.2f} font={bank['font'].split('+')[-1][:25]} size={bank['size']}")


def compare_total_line():
    print("\n" + "=" * 70)
    print("TOTAL LINE (Итого + amount + ruble)")
    for path in [FAKE] + ORIGS:
        sp = find_by_y(spans_detail(path), 106.61)
        print(f"  {path.name}:")
        for s in sp:
            print(f"    {s['text']!r:12s} font={s['font'].split('+')[-1][:20]:20s} "
                  f"size={s['size']} origin=({s['origin'][0]:.2f},{s['origin'][1]:.2f}) "
                  f"right={s['right']:.2f} h={s['h']:.2f} flags={s['flags']}")


if __name__ == "__main__":
    report_file(FAKE, "FAKE")
    for p in ORIGS:
        report_file(p, "ORIG")
    compare_bank_alignment()
    compare_total_line()
