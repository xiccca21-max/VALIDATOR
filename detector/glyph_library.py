"""
Per-bank glyph library: character -> set of exact glyph-outline signatures.

Idea (validated empirically): genuine receipts of the same bank are produced by
the same backend with the same embedded font, so the outline (contour points +
flags + advance width) of a given character is byte-stable across all originals.
A forgery made with a different font build (even the "same" font from another
source, or a re-hinted/re-subset copy) produces different outlines for common
characters. We therefore:

  * build a library {char: {outline_sig, ...}} from all originals of a bank;
  * for a new PDF, compare the outline of every character that also exists in
    the library;
  * raise a HARD signal only when many COMMON characters (digits + frequent
    Cyrillic letters that appear in essentially every receipt) do not match any
    known outline — i.e. the document was drawn with a foreign font.

This is deliberately conservative to never flag a genuine receipt: characters
not present in the library are ignored, and the hard signal needs a large,
unambiguous mismatch among high-frequency characters.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

# High-frequency characters present in virtually every Russian bank receipt.
# Used to decide whether a font is "foreign": these outlines must be known.
COMMON_CHARS = set("0123456789")
COMMON_CHARS |= set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
COMMON_CHARS |= set("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ")
COMMON_CHARS |= {".", ",", " ", "-", "+", "₽", "%", "№", ":", "(", ")"}

_LIB_DIR = Path(__file__).with_name("glyph_libraries")


def _outline_sig(font, gid: int) -> str | None:
    """Stable hash of a glyph outline (coords + flags + advance) by glyph id."""
    try:
        glyf = font["glyf"]
        order = font.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return None
        gname = order[gid]
        g = glyf[gname]
        try:
            g.expand(glyf)
        except Exception:
            pass
        if g.isComposite():
            payload = ("c", tuple(
                (c.glyphName, getattr(c, "x", 0), getattr(c, "y", 0))
                for c in g.components
            ))
        else:
            coords = tuple(getattr(g, "coordinates", []) or [])
            flags = tuple(int(x) for x in (getattr(g, "flags", []) or []))
            if not coords:
                return None
            adv = font["hmtx"][gname][0]
            payload = (coords, flags, adv)
        return hashlib.sha1(repr(payload).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _embedded_truetypes(pdf_bytes: bytes):
    """Yield fontTools.TTFont for each embedded TrueType (FontFile2) with glyf."""
    import fitz
    from fontTools.ttLib import TTFont

    fonts = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return fonts
    try:
        for xref in range(1, doc.xref_length()):
            try:
                key = doc.xref_object(xref, compressed=False) or ""
            except Exception:
                continue
            if "/Length1" in key and "/Filter" in key:
                try:
                    raw = doc.xref_stream(xref)
                    font = TTFont(io.BytesIO(raw))
                    if "glyf" in font and "hmtx" in font:
                        fonts.append(font)
                except Exception:
                    continue
    finally:
        doc.close()
    return fonts


def extract_char_glyphs(pdf_bytes: bytes) -> dict[str, set[str]]:
    """
    Map each drawn character -> set of glyph-outline signatures.

    Only handles the single-embedded-font case (covers VTB / Sber / Alfa /
    Gazprom / OTP / Ozon). Multi-font documents (e.g. T-Bank) return {} so the
    caller can rely on the dedicated engines instead.
    """
    import fitz

    fonts = _embedded_truetypes(pdf_bytes)
    if len(fonts) != 1:
        return {}
    font = fonts[0]

    out: dict[str, set[str]] = {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return {}
    try:
        for page in doc:
            try:
                trace = page.get_texttrace()
            except Exception:
                continue
            for span in trace:
                for ch in span.get("chars", []):
                    try:
                        ucs, gid = ch[0], ch[1]
                    except Exception:
                        continue
                    if ucs <= 0:
                        continue
                    sig = _outline_sig(font, gid)
                    if not sig:
                        continue
                    out.setdefault(chr(ucs), set()).add(sig)
    finally:
        doc.close()
    return out


def build_library(profiles: list[dict[str, set[str]]]) -> dict:
    """Merge per-file {char: {sig}} profiles into one bank library."""
    chars: dict[str, set[str]] = {}
    used = 0
    for prof in profiles:
        if not prof:
            continue
        used += 1
        for ch, sigs in prof.items():
            chars.setdefault(ch, set()).update(sigs)
    return {
        "version": 1,
        "source_count": used,
        "chars": {ch: sorted(sigs) for ch, sigs in chars.items()},
    }


def check_against_library(pdf_bytes: bytes, library: dict) -> tuple[list[str], dict]:
    """
    Compare a PDF's glyph outlines against a bank library.

    Returns (flags, stats). A single HARD flag GLYPH_LIBRARY_FOREIGN is emitted
    only on an unambiguous foreign-font signature among common characters.
    """
    ref = (library or {}).get("chars") or {}
    if not ref:
        return [], {"reason": "no_library"}

    cur = extract_char_glyphs(pdf_bytes)
    if not cur:
        return [], {"reason": "no_single_font"}

    common_compared = 0
    common_mismatch = 0
    mismatched_chars: list[str] = []
    for ch, sigs in cur.items():
        ref_sigs = set(ref.get(ch, []))
        if not ref_sigs:
            continue  # character never seen in originals -> ignore (safe)
        if ch not in COMMON_CHARS:
            continue  # only judge on high-frequency, always-present characters
        common_compared += 1
        if set(sigs).isdisjoint(ref_sigs):
            common_mismatch += 1
            mismatched_chars.append(ch)

    stats = {
        "common_compared": common_compared,
        "common_mismatch": common_mismatch,
        "mismatched_chars": "".join(sorted(mismatched_chars)),
        "source_count": library.get("source_count"),
    }

    flags: list[str] = []
    # Foreign-font decision: need a solid sample of common chars and a large
    # fraction of them wrong. Genuine receipts score exactly 0 mismatches.
    if common_compared >= 10 and common_mismatch >= 4 and (
        common_mismatch / common_compared
    ) >= 0.30:
        flags.append(
            "[GLYPH_LIBRARY_FOREIGN] шрифт документа не совпадает с эталоном банка: "
            f"{common_mismatch} из {common_compared} частых символов "
            f"(«{stats['mismatched_chars']}») имеют чужие контуры"
        )
    return flags, stats


def load_library_for(bank_key: str) -> dict:
    path = _LIB_DIR / f"{bank_key}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
