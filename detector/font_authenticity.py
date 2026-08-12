"""Per-bank authentic embedded-font library.

The check is intentionally based on stable TTF internals, not on subset size.
Subset size changes with receipt text; table identity and glyph program hashes
are much safer signals for detecting a foreign font.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .ff2_pool import extract_fontfile2_stream_blobs


_LIB_DIR = Path(__file__).with_name("font_libraries")
_MIN_HARD_SAMPLES = 8


@dataclass
class FontAuthFlag:
    code: str
    detail: str


@dataclass
class FontAuthCheck:
    flags: list[FontAuthFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _base_font_name(name: str) -> str:
    if not name:
        return ""
    base = name.split("+", 1)[-1].strip()
    # Quartz/iOS often emits per-file resource names like font000000002ff81462.
    # They are not a real font family and must not be used as a hard identity.
    if re.fullmatch(r"font[0-9a-fA-F]{8,}", base):
        return "embedded-quartz-font"
    return base


def _tables(ttf: bytes) -> dict[str, bytes]:
    if len(ttf) < 12:
        return {}
    try:
        num_tables = struct.unpack(">H", ttf[4:6])[0]
    except Exception:
        return {}
    out: dict[str, bytes] = {}
    off = 12
    for _ in range(num_tables):
        if off + 16 > len(ttf):
            break
        tag = ttf[off:off + 4].decode("latin1", "replace")
        try:
            table_off, table_len = struct.unpack(">II", ttf[off + 8:off + 16])
        except Exception:
            break
        data = ttf[table_off:table_off + table_len]
        if data:
            out[tag] = data
        off += 16
    return out


def _normalized_stable_table(tag: str, data: bytes) -> bytes:
    b = bytearray(data)
    if tag == "head":
        # checksumAdjustment and timestamps are expected to differ.
        if len(b) >= 12:
            b[8:12] = b"\x00\x00\x00\x00"
        if len(b) >= 36:
            b[20:36] = b"\x00" * 16
    elif tag == "hhea":
        # numOfLongHorMetrics changes with subset glyph count.
        if len(b) >= 36:
            b[34:36] = b"\x00\x00"
    elif tag == "maxp":
        # numGlyphs changes with subset glyph count.
        if len(b) >= 6:
            b[4:6] = b"\x00\x00"
    return bytes(b)


def _stable_table_hashes(tables: dict[str, bytes]) -> dict[str, str]:
    stable_tags = (
        "OS/2", "cmap", "cvt ", "fpgm", "gasp", "head",
        "hhea", "maxp", "name", "post", "prep",
    )
    return {
        tag: _sha16(_normalized_stable_table(tag, tables[tag]))
        for tag in stable_tags
        if tag in tables
    }


def _table_digest(stable_hashes: dict[str, str]) -> str:
    if not stable_hashes:
        return ""
    payload = "|".join(f"{k}:{stable_hashes[k]}" for k in sorted(stable_hashes))
    return _sha16(payload.encode("utf-8"))


def _glyph_hashes(ttf: bytes, tables: dict[str, bytes]) -> set[str]:
    """Return raw glyf-program hashes.

    This does not require cmap/name tables and does not care about subset size.
    It only says whether the actual outlines/programs are from a known font.
    """
    glyf = tables.get("glyf")
    loca = tables.get("loca")
    head = tables.get("head")
    maxp = tables.get("maxp")
    if not glyf or not loca or not head or not maxp or len(head) < 52 or len(maxp) < 6:
        return set()
    try:
        num_glyphs = struct.unpack(">H", maxp[4:6])[0]
        index_to_loc = struct.unpack(">h", head[50:52])[0]
    except Exception:
        return set()
    offsets: list[int] = []
    try:
        if index_to_loc == 0:
            need = (num_glyphs + 1) * 2
            if len(loca) < need:
                return set()
            offsets = [struct.unpack(">H", loca[i:i + 2])[0] * 2 for i in range(0, need, 2)]
        else:
            need = (num_glyphs + 1) * 4
            if len(loca) < need:
                return set()
            offsets = [struct.unpack(">I", loca[i:i + 4])[0] for i in range(0, need, 4)]
    except Exception:
        return set()
    out: set[str] = set()
    for a, b in zip(offsets, offsets[1:]):
        if b <= a or a < 0 or b > len(glyf):
            continue
        out.add(_sha16(glyf[a:b]))
    return out


def extract_font_auth_profile(pdf_bytes: bytes) -> dict:
    fonts = []
    for item in extract_fontfile2_stream_blobs(pdf_bytes):
        ttf = item.get("bytes")
        # extract_fontfile2_streams intentionally does not expose bytes in logs.
        if not ttf:
            continue
        tables = _tables(ttf)
        stable = _stable_table_hashes(tables)
        fonts.append({
            "font_name": item.get("font_name") or "",
            "base_name": _base_font_name(item.get("font_name") or ""),
            "ttf_sha16": item.get("sha256_16") or _sha16(ttf),
            "table_tags": sorted(tables),
            "stable_tables": stable,
            "stable_digest": _table_digest(stable),
            "glyph_hashes": sorted(_glyph_hashes(ttf, tables)),
        })
    return {"fonts": fonts}


def merge_font_auth_library(samples: list[dict]) -> dict:
    lib = {
        "version": 1,
        "source_count": len(samples),
        "fonts": {},
    }
    by_name: dict[str, dict] = {}
    for sample in samples:
        for font in sample.get("fonts") or []:
            base = font.get("base_name") or "unknown"
            slot = by_name.setdefault(base, {
                "source_count": 0,
                "stable_digests": set(),
                "stable_tables": {},
                "table_tags": set(),
                "glyph_hashes": set(),
                "ttf_sha16": set(),
            })
            slot["source_count"] += 1
            if font.get("stable_digest"):
                slot["stable_digests"].add(font["stable_digest"])
            if font.get("ttf_sha16"):
                slot["ttf_sha16"].add(font["ttf_sha16"])
            slot["table_tags"].update(font.get("table_tags") or [])
            slot["glyph_hashes"].update(font.get("glyph_hashes") or [])
            for tag, h in (font.get("stable_tables") or {}).items():
                slot["stable_tables"].setdefault(tag, set()).add(h)
    for base, slot in by_name.items():
        lib["fonts"][base] = {
            "source_count": slot["source_count"],
            "stable_digests": sorted(slot["stable_digests"]),
            "stable_tables": {
                tag: sorted(vals)
                for tag, vals in sorted(slot["stable_tables"].items())
            },
            "table_tags": sorted(slot["table_tags"]),
            "glyph_hashes": sorted(slot["glyph_hashes"]),
            "ttf_sha16": sorted(slot["ttf_sha16"]),
        }
    return lib


def load_font_library_for(bank_key: str, channel: str) -> dict:
    path = _LIB_DIR / f"{bank_key}_{channel}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def check_pdf_against_font_library(pdf_bytes: bytes, library: dict) -> FontAuthCheck:
    res = FontAuthCheck()
    prof = extract_font_auth_profile(pdf_bytes)
    ref_fonts = library.get("fonts") or {}
    source_count = int(library.get("source_count") or 0)
    hard_allowed = source_count >= _MIN_HARD_SAMPLES
    stats = {"source_count": source_count, "fonts": []}

    for cur in prof.get("fonts") or []:
        base = cur.get("base_name") or "unknown"
        ref = ref_fonts.get(base)
        cur_glyphs = set(cur.get("glyph_hashes") or [])
        stat = {
            "base_name": base,
            "glyph_count": len(cur_glyphs),
            "stable_digest": cur.get("stable_digest"),
            "known_name": bool(ref),
            "unknown_glyphs": None,
        }
        stats["fonts"].append(stat)

        if not ref:
            all_glyphs: set[str] = set()
            all_digests: set[str] = set()
            for candidate in ref_fonts.values():
                all_glyphs.update(candidate.get("glyph_hashes") or [])
                all_digests.update(candidate.get("stable_digests") or [])
            compared = len(cur_glyphs)
            unknown = len(cur_glyphs - all_glyphs) if all_glyphs else compared
            digest = cur.get("stable_digest") or ""
            stat["unknown_glyphs"] = unknown
            code = "FONT_AUTH_NAME_DRIFT"
            if (
                hard_allowed
                and digest not in all_digests
                and compared >= 15
                and unknown >= 8
                and (unknown / compared) >= 0.35
            ):
                code = "FONT_AUTH_FOREIGN_FONT"
            res.flags.append(FontAuthFlag(
                code,
                f"встроенный шрифт {base} не встречался в {source_count} эталонах канала",
            ))
            continue

        ref_digests = set(ref.get("stable_digests") or [])
        digest = cur.get("stable_digest") or ""
        if ref_digests and digest and digest not in ref_digests:
            ref_glyphs = set(ref.get("glyph_hashes") or [])
            compared = len(cur_glyphs)
            unknown = len(cur_glyphs - ref_glyphs) if ref_glyphs else 0
            stat["unknown_glyphs"] = unknown
            if hard_allowed and compared >= 15 and unknown >= 8 and (unknown / compared) >= 0.35:
                res.flags.append(FontAuthFlag(
                    "FONT_AUTH_FOREIGN_FONT",
                    f"{base}: стабильные таблицы и {unknown}/{compared} glyph-контуров вне библиотеки",
                ))
            else:
                res.flags.append(FontAuthFlag(
                    "FONT_AUTH_TABLE_DRIFT",
                    f"{base}: стабильные таблицы шрифта не совпали с эталоном",
                ))

    res.stats = stats
    return res
