#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from detector.profiles import analyze_for
from detector.structure import content_skeleton_hash, content_stream_bytes

GEN = Path(r"C:\Users\fanis\OneDrive\Desktop\22.06 генератор 4 из 5\_test10_ozon_fresh")
CORPUS = Path.home() / "OneDrive" / "Desktop" / "чеки" / "озонбанк"
FAKE = Path.home() / "OneDrive" / "Desktop" / "фейки" / "озоник.pdf"
SPEC = json.loads((ROOT / "detector" / "bank_specs" / "ozon.json").read_text(encoding="utf-8"))
KNOWN_SK = set(SPEC.get("skeleton_hashes_global", []))
SBP_DEC = SPEC["channels"]["sbp"]["content_decoded"]
OBJ_LO, OBJ_HI = SPEC["object_count"]


def metrics(path: Path) -> dict:
    b = path.read_bytes()
    doc = fitz.open(stream=b, filetype="pdf")
    text = doc[0].get_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    meta = doc.metadata or {}
    doc.close()
    cs = content_stream_bytes(b)
    dec = len(cs) if cs else 0
    return {
        "file": path.name,
        "size": len(b),
        "objs": len(re.findall(rb"\d+ 0 obj", b)),
        "producer": meta.get("producer", ""),
        "skeleton": content_skeleton_hash(b),
        "content_decoded": dec,
        "lines": lines[:25],
        "has_gteesti": bool(re.search(rb"GTEesti", b)),
        "has_skia": b"Skia/PDF" in b,
    }


def main() -> None:
    pdfs = sorted(GEN.glob("*.pdf"))
    print(f"Generated PDFs: {len(pdfs)} in {GEN}\n")

    corp = [metrics(p) for p in sorted(CORPUS.glob("*.pdf"))]
    sbp_corp = [c for c in corp if c["content_decoded"] >= SBP_DEC[0] - 100]
    print("=== CORPUS SBP envelope ===")
    print(f"  size: {min(c['size'] for c in sbp_corp)} – {max(c['size'] for c in sbp_corp)}")
    print(f"  objs: {sorted(set(c['objs'] for c in sbp_corp))}")
    print(f"  decoded: {SBP_DEC}")
    print(f"  skeletons: {sorted(set(c['skeleton'] for c in sbp_corp))}\n")

    issues_all: list[str] = []
    clean = fake = 0

    for p in pdfs:
        m = metrics(p)
        r = analyze_for("ozon", p.read_bytes())
        m["verdict"] = r["verdict"]
        m["flags"] = r.get("flags") or []
        m["score"] = r.get("score")
        sk_ok = m["skeleton"] in KNOWN_SK if m["skeleton"] else False
        dec_ok = SBP_DEC[0] <= m["content_decoded"] <= SBP_DEC[1] + 200
        obj_ok = OBJ_LO <= m["objs"] <= OBJ_HI
        prod_ok = "Skia" in m["producer"]

        issues: list[str] = []
        if m["verdict"] == "ФЕЙК":
            issues.append(f"VERDICT FAKE: {m['flags'][:3]}")
        if not sk_ok:
            issues.append(f"skeleton unknown: {m['skeleton']}")
        if not dec_ok:
            issues.append(f"content_decoded {m['content_decoded']} outside {SBP_DEC}")
        if not obj_ok:
            issues.append(f"objects {m['objs']} outside {OBJ_LO}-{OBJ_HI}")
        if not prod_ok:
            issues.append(f"producer {m['producer']!r}")
        if not m["has_gteesti"]:
            issues.append("GTEesti missing")
        if not m["has_skia"]:
            issues.append("Skia/PDF missing in bytes")

        # text sanity
        text = "\n".join(m["lines"])
        if "Без комиссии" not in text and "₽" not in text:
            issues.append("commission line odd")
        if m["file"] == "09_15000_comm.pdf" and "15" not in text:
            issues.append("commission case 09: expected fee visible")

        status = "OK" if not issues else "ISSUES"
        if m["verdict"] == "ЧИСТО":
            clean += 1
        else:
            fake += 1

        print(f"[{status}] {m['file']}")
        print(f"  verdict={m['verdict']} score={m['score']} size={m['size']} objs={m['objs']} dec={m['content_decoded']}")
        print(f"  skeleton={m['skeleton']} in_corpus={sk_ok}")
        if issues:
            for i in issues:
                print(f"  ! {i}")
                issues_all.append(f"{m['file']}: {i}")
        print()

    print(f"=== SUMMARY: PROTON clean {clean}/{len(pdfs)}, fake {fake}/{len(pdfs)} ===")
    if issues_all:
        print(f"Structural issues: {len(issues_all)}")
        for i in issues_all[:20]:
            print(" ", i)

    if FAKE.exists():
        fr = analyze_for("ozon", FAKE.read_bytes())
        print(f"\nControl fake озоник.pdf: {fr['verdict']} {fr.get('flags', [])[:3]}")


if __name__ == "__main__":
    main()
