"""
Per-bank/channel symbol library based on CID/CMap/glyf fingerprints.

This module is intentionally conservative: it builds and validates symbol
profiles but does not force a FAKE verdict by itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .glyf_fingerprint import (
    _collect_used_by_font,
    _extract_fontfile2,
    _font_cid_maps,
    _glyf_md5_by_gid,
)

FONT_KEYS = ("F1", "F2", "F3")


@dataclass
class SymbolFlag:
    code: str
    detail: str


@dataclass
class SymbolCheck:
    flags: list[SymbolFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def extract_symbol_profile(pdf_bytes: bytes) -> dict:
    """Extract per-font CID/CMap/glyf profile from one PDF."""
    cid_maps = _font_cid_maps(pdf_bytes)
    used_by_font = _collect_used_by_font(pdf_bytes)

    out: dict = {"fonts": {}}
    for font_key in FONT_KEYS:
        cmap = cid_maps.get(font_key, {})
        used = sorted(used_by_font.get(font_key, set()))
        ttf = _extract_fontfile2(pdf_bytes, font_key)
        if not cmap or not ttf:
            continue

        import hashlib

        ttf_sha = hashlib.sha256(ttf).hexdigest()[:16]
        font_out: dict = {
            "cmap_cids": len(cmap),
            "used_cids": len(used),
            "ttf_size": len(ttf),
            "ttf_sha16": ttf_sha,
            "chars": {},
        }

        for cid in used:
            ch = cmap.get(cid)
            if not ch:
                continue
            # Keep only printable single-char symbols for stable matching.
            if len(ch) != 1 or not ch.isprintable():
                continue
            gm = _glyf_md5_by_gid(ttf, cid)
            if not gm:
                continue
            slot = font_out["chars"].setdefault(ch, set())
            slot.add(gm)

        font_out["chars"] = {
            ch: sorted(hashes)
            for ch, hashes in font_out["chars"].items()
        }
        out["fonts"][font_key] = font_out
    return out


def merge_symbol_library(samples: list[dict]) -> dict:
    """Merge multiple extracted profiles into one corpus library."""
    lib = {
        "version": 1,
        "source_count": len(samples),
        "fonts": {},
    }

    for font_key in FONT_KEYS:
        cmap_vals: list[int] = []
        used_vals: list[int] = []
        ttf_sizes: list[int] = []
        ttf_shas: set[str] = set()
        chars_acc: dict[str, set[str]] = {}

        for s in samples:
            f = (s.get("fonts") or {}).get(font_key)
            if not f:
                continue
            cmap_vals.append(int(f.get("cmap_cids") or 0))
            used_vals.append(int(f.get("used_cids") or 0))
            ttf_sizes.append(int(f.get("ttf_size") or 0))
            if f.get("ttf_sha16"):
                ttf_shas.add(f["ttf_sha16"])
            for ch, hashes in (f.get("chars") or {}).items():
                chars_acc.setdefault(ch, set()).update(hashes or [])

        if not cmap_vals:
            continue
        lib["fonts"][font_key] = {
            "cmap_cids": [min(cmap_vals), max(cmap_vals)],
            "used_cids": [min(used_vals), max(used_vals)],
            "ttf_size": [min(ttf_sizes), max(ttf_sizes)],
            "ttf_sha16": sorted(ttf_shas),
            "chars": {
                ch: sorted(hs)
                for ch, hs in chars_acc.items()
            },
        }

    return lib


def check_pdf_against_library(pdf_bytes: bytes, library: dict) -> SymbolCheck:
    """
    Compare one PDF against a symbol library.
    Conservative default: emit drift signals only.
    """
    res = SymbolCheck()
    prof = extract_symbol_profile(pdf_bytes)
    stats: dict = {"fonts": {}}

    for font_key, ref in (library.get("fonts") or {}).items():
        cur = (prof.get("fonts") or {}).get(font_key)
        if not cur:
            res.flags.append(SymbolFlag(
                "SYMBOL_FONT_MISSING",
                f"в профиле не найден {font_key}, хотя он есть в эталоне",
            ))
            continue

        fstats = {"unknown_chars": 0, "compared_chars": 0}
        stats["fonts"][font_key] = fstats

        # Size range (soft signal)
        lo, hi = ref.get("ttf_size", [0, 0])
        sz = int(cur.get("ttf_size") or 0)
        if lo and hi and not (lo <= sz <= hi):
            res.flags.append(SymbolFlag(
                "SYMBOL_TTF_SIZE_DRIFT",
                f"{font_key} FontFile2 {sz} B вне эталона {lo}-{hi}",
            ))

        # Per-character glyf hashes
        for ch, cur_hashes in (cur.get("chars") or {}).items():
            ref_hashes = set((ref.get("chars") or {}).get(ch, []))
            if not ref_hashes:
                continue
            fstats["compared_chars"] += 1
            if set(cur_hashes).isdisjoint(ref_hashes):
                fstats["unknown_chars"] += 1

        compared = fstats["compared_chars"]
        unknown = fstats["unknown_chars"]
        if compared >= 12 and unknown >= 3 and (unknown / compared) >= 0.20:
            res.flags.append(SymbolFlag(
                "SYMBOL_GLYPH_DRIFT",
                f"{font_key}: {unknown}/{compared} символов имеют контуры вне библиотеки",
            ))

    res.stats = stats
    return res


def load_symbol_library(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_symbol_library_for(bank_key: str, channel: str) -> dict:
    path = Path(__file__).with_name("symbol_libraries") / f"{bank_key}_{channel}.json"
    return load_symbol_library(path)
