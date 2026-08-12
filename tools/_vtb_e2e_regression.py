#!/usr/bin/env python3
"""End-to-end VTB fake regression via production entry points.

Tests route() → reputation → _normalize_binary_result → user message,
NOT just analyze_vtb_v* internals.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VTB_V2_ROLLOUT"] = "100"
os.environ["VTB_V1_ROLLOUT"] = "100"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from detector import route  # noqa: E402
from detector import reputation  # noqa: E402
from detector.hardening_v2.verdict_merge import apply_v2_priority  # noqa: E402

# Import bot helpers without starting the bot polling loop.
import bot as bot_mod  # noqa: E402

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\втб")
FAKE_SRC = [
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки\ВТБ фейк.pdf"),
    Path(r"C:\Users\fanis\OneDrive\Desktop\фейки\втб сбп.pdf"),
]
OUT = ROOT / "tools" / "_vtb_e2e_regression.json"

EXPECTED_SHA = {
    "9ddc4942d9248cc6037734a2aadb0ff1d12419581189759ef291f5cc9da57286",
    "0f6562768c2c26d2bb3c568819cd7fdbe2e22083c3ff677d15f84b2cd3bf4db9",
}


def _pipe(pdf_bytes: bytes) -> tuple[str, dict, str]:
    bank, result, is_tbank = route(pdf_bytes)
    rep = reputation.check_known_fake(pdf_bytes, "")
    result = dict(result)
    result["score"] = int(result.get("score") or 0) + int(rep.get("score") or 0)
    result["flags"] = list(result.get("flags") or []) + list(rep.get("flags") or [])
    if rep.get("known_fake") or int(rep.get("score") or 0) >= 95:
        details = dict(result.get("details") or {})
        details["known_fake_count"] = max(int(details.get("known_fake_count") or 0), 1)
        details["verdict_after_reputation"] = "ФЕЙК"
        result["details"] = details
        result["verdict"] = "ФЕЙК"
        result["emoji"] = "🔴"
        result["score"] = max(int(result.get("score") or 0), 95)
    result = apply_v2_priority(result)
    result = bot_mod._normalize_binary_result(result)
    text = bot_mod._format_result(
        pdf_bytes, result, bank, is_tbank, False, username=None, user_id=0,
    )
    return bank, result, text


def main() -> int:
    rows = []
    ok = True

    # 1) originals
    for p in sorted(CORPUS.glob("*.pdf")):
        bank, r, text = _pipe(p.read_bytes())
        row = {
            "file": p.name, "kind": "original", "bank": bank,
            "verdict": r["verdict"], "score": r["score"], "flags": r.get("flags"),
            "engine": (r.get("details") or {}).get("engine"),
            "user": text.replace("\n", " | ")[:200],
        }
        rows.append(row)
        if r["verdict"] != "ЧИСТО" or "Подделка" in text:
            ok = False

    # 2) fakes + renamed byte-copies
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        fake_paths = []
        for src in FAKE_SRC:
            if not src.exists():
                ok = False
                rows.append({"file": src.name, "kind": "fake", "error": "missing"})
                continue
            fake_paths.append(src)
            # renamed copies
            for suffix in ("(1)", "(2)"):
                dst = tdir / f"{src.stem}{suffix}.pdf"
                shutil.copy2(src, dst)
                fake_paths.append(dst)

        for p in fake_paths:
            data = p.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            bank, r, text = _pipe(data)
            d = r.get("details") or {}
            shadow = d.get("vtb_v1_shadow") or d.get("vtb_v2_shadow") or {}
            shadow_hide = (
                (shadow.get("v1_verdict") == "ФЕЙК" or shadow.get("v2_verdict") == "ФЕЙК")
                and r.get("verdict") == "ЧИСТО"
            )
            row = {
                "file": p.name,
                "kind": "fake",
                "sha": sha,
                "sha_known": sha in EXPECTED_SHA,
                "bank": bank,
                "verdict": r["verdict"],
                "score": r["score"],
                "engine": d.get("engine"),
                "hard_count": d.get("hard_count"),
                "known_fake_count": d.get("known_fake_count"),
                "flags": r.get("flags"),
                "shadow_hide_bug": shadow_hide,
                "user": text.replace("\n", " | ")[:240],
            }
            rows.append(row)
            if bank != "Банк ВТБ":
                ok = False
            if r["verdict"] != "ФЕЙК" or int(r.get("score") or 0) < 95:
                ok = False
            if not (
                int(d.get("known_fake_count") or 0) >= 1
                or int(d.get("hard_count") or 0) >= 1
                or any("KNOWN" in str(f).upper() or "VTB_METHOD_" in str(f) for f in (r.get("flags") or []))
            ):
                ok = False
            if "Подделка" not in text or "Оригинал" in text:
                ok = False
            if shadow_hide:
                ok = False

    summary = {
        "ok": ok,
        "originals_clean": sum(1 for r in rows if r.get("kind") == "original" and r.get("verdict") == "ЧИСТО"),
        "fakes_caught": sum(1 for r in rows if r.get("kind") == "fake" and r.get("verdict") == "ФЕЙК"),
        "rows": rows,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("ok", "originals_clean", "fakes_caught")},
                     ensure_ascii=False, indent=2))
    for r in rows:
        if r.get("kind") == "fake" or r.get("verdict") != "ЧИСТО":
            print(r.get("kind"), r.get("file"), r.get("verdict"), r.get("score"),
                  r.get("engine"), (r.get("flags") or [])[:1])
    print("wrote", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
