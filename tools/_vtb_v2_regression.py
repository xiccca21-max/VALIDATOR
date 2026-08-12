#!/usr/bin/env python3
"""VTB v2 regression: 15 originals ЧИСТО + known fakes ФЕЙК."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VTB_V2_ROLLOUT", "100")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from detector.hardening_v2.verdict_merge import apply_v2_priority  # noqa: E402
from detector.vtb import analyze  # noqa: E402

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\втб")
FAKES = [
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки\ВТБ фейк.pdf"),
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки\втб сбп.pdf"),
]
OUT = ROOT / "tools" / "_vtb_v2_regression.json"


def main() -> int:
    rows = []
    ok = True

    for p in sorted(CORPUS.glob("*.pdf")):
        r = apply_v2_priority(analyze(p.read_bytes()))
        d = r.get("details") or {}
        row = {
            "file": p.name,
            "kind": "original",
            "verdict": r["verdict"],
            "flags": r.get("flags") or [],
            "engine": d.get("engine"),
            "subtype": d.get("subtype"),
            "rollout_mode": d.get("rollout_mode"),
        }
        rows.append(row)
        if r["verdict"] != "ЧИСТО" or r.get("flags"):
            ok = False

    for p in FAKES:
        if not p.exists():
            ok = False
            rows.append({"file": p.name, "kind": "fake", "error": "missing"})
            continue
        r = apply_v2_priority(analyze(p.read_bytes()))
        d = r.get("details") or {}
        flags = r.get("flags") or []
        row = {
            "file": p.name,
            "kind": "fake",
            "verdict": r["verdict"],
            "flags": flags,
            "engine": d.get("engine"),
            "subtype": d.get("subtype"),
            "known_fake_count": d.get("known_fake_count"),
            "hard_count": d.get("hard_count"),
        }
        rows.append(row)
        if r["verdict"] != "ФЕЙК":
            ok = False
        if p.name == "ВТБ фейк.pdf" and not any("VTB_KNOWN_" in f for f in flags):
            ok = False
        if p.name == "втб сбп.pdf" and not any(
            code in f
            for f in flags
            for code in (
                "VTB_METHOD_SBP_TO_SELF_BANK",
                "VTB_METHOD_FIELDSET_COLLISION",
                "VTB_SBP_LINKED_TUPLE_KNOWN_FAKE",
            )
        ):
            ok = False

    summary = {
        "ok": ok,
        "originals": Counter(r["verdict"] for r in rows if r.get("kind") == "original"),
        "fakes": Counter(r["verdict"] for r in rows if r.get("kind") == "fake"),
        "empty_flag_originals": sum(
            1 for r in rows if r.get("kind") == "original" and not r.get("flags")
        ),
        "rows": rows,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("ok", "originals", "fakes", "empty_flag_originals")},
                     ensure_ascii=False, indent=2))
    print(f"wrote {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
