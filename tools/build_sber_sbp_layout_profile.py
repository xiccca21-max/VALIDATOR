#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build detector/bank_specs/sber_sbp_layout.json from genuine Sber SBP receipts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.profiles import analyze, reload_profiles
from detector.sber_sbp_layout import extract_layout_features

CHEKI = Path(os.environ.get("CHEKI_DIR", Path.home() / "OneDrive" / "Desktop" / "чеки"))
SBER_DIR = CHEKI / "сбер"
OUT = ROOT / "detector" / "bank_specs" / "sber_sbp_layout.json"


def _env_int(vals: list[int], pad: int = 0) -> list[int] | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return [min(vals) - pad, max(vals) + pad]


def _env_float(vals: list[float], pad: float = 0.0) -> list[float] | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return [round(min(vals) - pad, 5), round(max(vals) + pad, 5)]


def main() -> int:
    if not SBER_DIR.is_dir():
        print(f"Folder not found: {SBER_DIR}")
        return 1

    reload_profiles()
    samples: list[dict] = []
    used_files: list[str] = []

    for p in sorted(SBER_DIR.glob("*.pdf")):
        data = p.read_bytes()
        r = analyze(data, p.stem)
        d = r.get("details") or {}
        if d.get("bank_key") != "sber" or d.get("channel") != "sbp":
            continue
        feats = extract_layout_features(data)
        if not feats:
            print(f"  SKIP {p.name} (no features)")
            continue
        samples.append(feats)
        used_files.append(p.name)
        print(
            f"  OK {p.name} size={feats.get('content_size')} "
            f"tm={feats.get('tm_count')} tj={feats.get('tj_count')}"
        )

    if not samples:
        print("No Sber SBP samples found")
        return 1

    ops_env = {
        "content_size": _env_int([int(s.get("content_size") or 0) for s in samples], 8),
        "tm_count": _env_int([int(s.get("tm_count") or 0) for s in samples], 1),
        "tj_count": _env_int([int(s.get("tj_count") or 0) for s in samples], 1),
    }

    label_keys = sorted({
        k for s in samples for k in (s.get("labels_norm_y") or {}).keys()
    })
    labels_env = {}
    for key in label_keys:
        vals = [float((s.get("labels_norm_y") or {}).get(key)) for s in samples if (s.get("labels_norm_y") or {}).get(key) is not None]
        env = _env_float(vals, 0.006)
        if env:
            labels_env[key] = env

    profile = {
        "version": 1,
        "bank_key": "sber",
        "channel": "sbp",
        "source_count": len(samples),
        "source_files": used_files,
        "ops_envelope": ops_env,
        "operator_signatures": sorted({
            s.get("operator_signature")
            for s in samples
            if s.get("operator_signature")
        }),
        "labels_norm_y": labels_env,
    }
    OUT.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT} ({len(samples)} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
