#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Собирает detector/bank_specs/alfa_ios.json из Quartz-чеков папки чеки/альфа."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from detector.bank_channels import detect_channel
from detector.structure import find_streams, is_content_stream, content_skeleton_hash

CHEKI = Path.home() / "OneDrive" / "Desktop" / "чеки" / "альфа"
OUT = ROOT / "detector" / "bank_specs" / "alfa_ios.json"


def _env(vals, pad):
    vals = [v for v in vals if v]
    if not vals:
        return None
    return [max(0, min(vals) - pad), max(vals) + pad]


def metrics(b, text):
    dec = 0
    for _, d in find_streams(b):
        if d and is_content_stream(d):
            dec = max(dec, len(d))
    return {
        "channel": detect_channel(text),
        "object_count": len(re.findall(rb"\d+ 0 obj", b)),
        "content_decoded": dec or None,
        "content_skeleton": content_skeleton_hash(b),
    }


def main():
    samples = []
    for pdf in sorted(CHEKI.glob("*.pdf")):
        b = pdf.read_bytes()
        doc = fitz.open(stream=b, filetype="pdf")
        prod = (doc.metadata or {}).get("producer", "") or ""
        text = "".join(p.get_text() for p in doc)
        doc.close()
        if "quartz" not in prod.lower():
            continue
        tl = text.replace("\xa0", " ").lower()
        if not ("сформирована" in tl and "квитанция о переводе" in tl):
            continue
        m = metrics(b, text)
        m["file"] = pdf.name
        samples.append(m)
        print(f"  {pdf.name:28} ch={m['channel']} obj={m['object_count']} dec={m['content_decoded']}")

    if not samples:
        print("NO alfa iOS samples found")
        return

    by_ch = {}
    for s in samples:
        by_ch.setdefault(s["channel"], []).append(s)
    channels, skel = {}, {}
    for ch, chs in by_ch.items():
        channels[ch] = {
            "samples": [x["file"] for x in chs],
            "content_decoded": _env([x["content_decoded"] for x in chs if x["content_decoded"]], 400),
        }
        skel[ch] = sorted({x["content_skeleton"] for x in chs if x.get("content_skeleton")})

    spec = {
        "version": "bank_spec_2026_06",
        "key": "alfa_ios",
        "name": "Альфа-Банк",
        "folder": "альфа",
        "sample_count": len(samples),
        "native_producers": ["quartz pdfcontext"],
        "required_fonts": [],
        "object_count": _env([s["object_count"] for s in samples], 2),
        "content_decoded_global": _env([s["content_decoded"] for s in samples if s["content_decoded"]], 400),
        "channels": channels,
        "skeleton_hashes": skel,
        "skeleton_hashes_global": sorted({s["content_skeleton"] for s in samples if s.get("content_skeleton")}),
        "sbp_cipher": True,
        "require_content_stream": False,
        "date_prefer_first_line": False,
        "reject_jasper_clone": False,
        "ignore_openaction": False,
        "required_fonts_any": False,
        "allow_empty_producer": False,
        "image_based": False,
        "fontfile2_profile": False,
        "excluded": [],
    }
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} ({len(samples)} samples)")


if __name__ == "__main__":
    main()
