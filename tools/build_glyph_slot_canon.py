"""Build F1/F2 Unicode→GID→outline→metrics canon for slot-transplant checks."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fontTools.ttLib import TTFont

from detector.font_layers import _font_objects
from detector.glyf_fingerprint import _extract_fontfile2, _font_cid_maps
from detector.pdf_forensics import _glyph_outline_hash

RULE_ID = "A-FONT-GLYPH-SLOT-TRANSPLANT-001"
VERSION = "1.0.0"
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
OUT = Path(__file__).resolve().parents[1] / "detector" / "atlas_data" / "tbank_glyph_slot_canon.json"
FONT_KEYS = ("F1", "F2")


def _merged_cmap(pdf: bytes, font_key: str, fonts: dict) -> dict[int, str]:
    out = dict(_font_cid_maps(pdf).get(font_key, {}))
    for cid, ch in (fonts.get(font_key, {}).get("cmap") or {}).items():
        if ch:
            out[cid] = ch
    return out


def build_corpus(corpus_dir: Path) -> dict:
    tallies: dict[str, dict[int, dict[tuple, int]]] = {
        fk: defaultdict(lambda: defaultdict(int)) for fk in FONT_KEYS
    }
    samples = 0
    for path in sorted(corpus_dir.glob("*.pdf")):
        data = path.read_bytes()
        fonts, _ = _font_objects(data)
        samples += 1
        for font_key in FONT_KEYS:
            ttf = _extract_fontfile2(data, font_key)
            if not ttf:
                continue
            cmap = _merged_cmap(data, font_key, fonts)
            try:
                tt = TTFont(BytesIO(ttf))
                order = tt.getGlyphOrder()
            except Exception:
                continue
            for cid, ch in cmap.items():
                if not ch or not ch.strip() or ch in " \t\r\n\u00a0\u202f":
                    continue
                cp = ord(ch[0])
                gid = cid
                if gid < 0 or gid >= len(order):
                    continue
                g = tt["glyf"][order[gid]]
                if int(getattr(g, "numberOfContours", 0) or 0) == 0:
                    continue
                try:
                    g.expand(tt["glyf"])
                except Exception:
                    pass
                oh = _glyph_outline_hash(ttf, gid) or ""
                if not oh:
                    continue
                adv, lsb = tt["hmtx"][order[gid]]
                key = (gid, oh, int(adv), int(lsb), int(g.xMin), int(g.xMax))
                tallies[font_key][cp][key] += 1

    fonts_out: dict[str, dict[str, dict]] = {}
    for font_key in FONT_KEYS:
        glyphs: dict[str, dict] = {}
        for cp, counts in tallies[font_key].items():
            if not counts:
                continue
            (gid, oh, adv, lsb, xmin, xmax), n = max(counts.items(), key=lambda x: x[1])
            glyphs[f"{cp:04X}"] = {
                "unicode": chr(cp),
                "gid": gid,
                "outline_norm_hash": oh,
                "hmtx_advanceWidth": adv,
                "hmtx_lsb": lsb,
                "glyph_xMin": xmin,
                "glyph_xMax": xmax,
                "corpus_n": n,
            }
        fonts_out[font_key] = glyphs

    return {
        "version": VERSION,
        "rule_id": RULE_ID,
        "corpus_dir": str(corpus_dir),
        "corpus_samples": samples,
        "fonts": fonts_out,
    }


def main() -> int:
    if not CORPUS.is_dir():
        print("MISSING corpus", CORPUS)
        return 1
    data = build_corpus(CORPUS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = sum(len(v) for v in data["fonts"].values())
    print(f"Wrote {OUT} ({n} glyphs from {data['corpus_samples']} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
