"""A-FONT-USED-CID-EMPTY-GLYPH-001 / A-VIS-TEXT-GLYPH-PARITY-001 — used CID glyf + text parity."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .font_layers import _font_objects
from .glyf_fingerprint import _collect_used_by_font, _extract_fontfile2, _font_cid_maps
from .structure import content_stream_bytes
from .tbank_jasper_profile import claims_confirmed_tbank_profile
from .tbank_sbp_geometry import _parse_content_runs

RULE_EMPTY = "A-FONT-USED-CID-EMPTY-GLYPH-001"
RULE_PARITY = "A-VIS-TEXT-GLYPH-PARITY-001"
_CODE_EMPTY = "USED_CID_EMPTY_GLYPH"
_CODE_PARITY = "TBANK_TEXT_GLYPH_PARITY"
_FONT_KEYS = ("F1", "F2")
_WHITESPACE = frozenset(" \t\r\n\u00a0\u202f")
_CRITICAL_LABELS = ("отправитель", "получатель")
_NAME_VALUE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё.\-\s]+$")


@dataclass
class IntegrityFlag:
    code: str
    detail: str
    rule_id: str = ""


@dataclass
class UsedGlyphIntegrityResult:
    flags: list[IntegrityFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _merged_cmap(pdf: bytes, font_key: str, fonts: dict) -> dict[int, str]:
    out = dict(_font_cid_maps(pdf).get(font_key, {}))
    for cid, ch in (fonts.get(font_key, {}).get("cmap") or {}).items():
        if ch:
            out[cid] = ch
    return out


def _cid_to_gid(pdf: bytes, font_key: str, cid: int) -> int:
    """Identity unless /CIDToGIDMap /Identity is absent (then still Identity for T-Bank Jasper)."""
    return cid


def _loca_glyph_length(ttf: bytes, gid: int) -> tuple[int, int, bool, str]:
    """
    Return (loca_slice_len, contour_count, missing, glyph_name).
    Uses loca[GID]:loca[GID+1] when available.
    """
    if not TTFont or not ttf:
        return 0, 0, True, ""
    try:
        tt = TTFont(BytesIO(ttf))
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return 0, 0, True, f"gid>{len(order)}"
        gname = order[gid]
        g = tt["glyf"][gname]
        try:
            g.expand(tt["glyf"])
        except Exception:
            pass
        contours = int(getattr(g, "numberOfContours", 0) or 0)
        raw = b""
        if hasattr(g, "compile"):
            try:
                raw = g.compile(tt["glyf"]) or b""
            except Exception:
                raw = b""
        loca_len = len(raw)
        if "loca" in tt and loca_len == 0:
            loca = tt["loca"]
            if gid + 1 < len(loca):
                loca_len = max(0, int(loca[gid + 1]) - int(loca[gid]))
        missing = gname in (".notdef",) and contours <= 0 and loca_len == 0
        return loca_len, contours, missing, gname
    except Exception as exc:
        return 0, 0, True, str(exc)


def _glyph_is_empty(loca_len: int, contours: int, missing: bool) -> bool:
    if missing:
        return True
    if contours < 0:
        # Composite glyph — empty only if loca slice is zero-length.
        return loca_len == 0
    return contours == 0 and loca_len == 0


def _is_non_space_char(ch: str) -> bool:
    if not ch:
        return False
    return ch not in _WHITESPACE


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _fitz_words(pdf: bytes) -> list[tuple[float, float, str]]:
    if not fitz:
        return []
    out: list[tuple[float, float, str]] = []
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
        page = doc[0] if doc.page_count else None
        if page:
            for w in page.get_text("words"):
                out.append((float(w[0]), float(w[1]), w[4]))
        doc.close()
    except Exception:
        pass
    return out


def _content_y_to_fitz_y(content_y: float, pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return content_y - 80.78
    best: float | None = None
    best_dy = 999.0
    for cy, fy in pairs:
        dy = abs(cy - content_y)
        if dy < best_dy:
            best_dy = dy
            best = fy - cy
    if best is None:
        return content_y - 80.78
    return content_y + best


def _calibrate_y_offset(runs: list[dict], fitz_words: list[tuple[float, float, str]]) -> float:
    pairs: list[tuple[float, float]] = []
    for r in runs:
        if r.get("x", 0) < 100:
            continue
        rt = _norm_text(r.get("text", ""))
        if len(rt) < 4:
            continue
        for fx, fy, fw in fitz_words:
            if fx < 100:
                continue
            if _norm_text(fw) == rt or rt in _norm_text(fw) or _norm_text(fw) in rt:
                pairs.append((float(r["y"]), fy))
                break
    if not pairs:
        return -80.78
    deltas = [fy - cy for cy, fy in pairs]
    return sum(deltas) / len(deltas)


def _label_rows(
    runs: list[dict],
    fitz_words: list[tuple[float, float, str]],
    y_offset: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in runs:
        if r.get("x", 0) > 80:
            continue
        label = _norm_text(r.get("text", ""))
        if not any(lbl in label for lbl in _CRITICAL_LABELS):
            continue
        fitz_y = float(r["y"]) + y_offset
        rows.append({
            "label": label,
            "content_y": float(r["y"]),
            "fitz_y": fitz_y,
        })
    return rows


def _value_text_content(runs: list[dict], cmap: dict[int, str], content_y: float) -> str:
    parts: list[str] = []
    for r in runs:
        if r.get("font") not in _FONT_KEYS:
            continue
        if r.get("x", 0) < 160:
            continue
        if abs(float(r["y"]) - content_y) > 2.5:
            continue
        t = r.get("text") or ""
        if not t.strip():
            t = "".join(cmap.get(c, "") for c in r.get("cids", []))
        parts.append(t.strip())
    return " ".join(p for p in parts if p)


def _value_text_fitz(fitz_words: list[tuple[float, float, str]], fitz_y: float) -> str:
    parts = [
        fw for fx, fy, fw in fitz_words
        if fx > 160 and abs(fy - fitz_y) <= 2.5 and fw.strip()
    ]
    return " ".join(parts)


def check_used_cid_empty_glyph(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> UsedGlyphIntegrityResult:
    """Every used CID (content stream) must have non-empty glyf for non-space ToUnicode."""
    out = UsedGlyphIntegrityResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out
    if not TTFont:
        out.stats["skipped"] = "no_fonttools"
        return out

    fonts, _ = _font_objects(pdf_bytes)
    used_by_font = _collect_used_by_font(pdf_bytes)
    checked = 0
    empty_hits: list[dict[str, Any]] = []

    for font_key in _FONT_KEYS:
        ttf = _extract_fontfile2(pdf_bytes, font_key)
        if not ttf:
            continue
        cmap = _merged_cmap(pdf_bytes, font_key, fonts)
        w_dict: dict[int, int] = {}
        dw: int | None = None
        try:
            from .tbank_glyph_atlas import _font_w_and_dw
            w_dict, dw, _ = _font_w_and_dw(pdf_bytes, font_key)
        except Exception:
            pass

        for cid in sorted(used_by_font.get(font_key, ())):
            ch = cmap.get(cid, "")
            if not _is_non_space_char(ch):
                continue
            gid = _cid_to_gid(pdf_bytes, font_key, cid)
            loca_len, contours, missing, gname = _loca_glyph_length(ttf, gid)
            checked += 1
            if not _glyph_is_empty(loca_len, contours, missing):
                continue
            pdf_w = w_dict.get(cid, dw)
            cp = ord(ch[0])
            empty_hits.append({
                "font": font_key,
                "cid": cid,
                "gid": gid,
                "unicode": ch,
                "codepoint": f"U+{cp:04X}",
                "loca_len": loca_len,
                "contours": contours,
                "pdf_w": pdf_w,
            })
            out.flags.append(IntegrityFlag(
                _CODE_EMPTY,
                (
                    f"{font_key}: CID/GID {cid} ToUnicode {ch!r} ({cp:04X}) — "
                    f"glyf length {loca_len}, contours={contours} "
                    f"(/{gname}); /W={pdf_w}"
                ),
                rule_id=RULE_EMPTY,
            ))

    out.stats["checked_used_cids"] = checked
    out.stats["empty_glyph_hits"] = empty_hits
    return out


def check_text_glyph_parity(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> UsedGlyphIntegrityResult:
    """Critical field values: ToUnicode-decoded content must match fitz-visible text."""
    out = UsedGlyphIntegrityResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out
    if not fitz:
        out.stats["skipped"] = "no_fitz"
        return out

    fonts, _ = _font_objects(pdf_bytes)
    content = content_stream_bytes(pdf_bytes) or b""
    runs = _parse_content_runs(content, fonts) if content else []
    fitz_words = _fitz_words(pdf_bytes)
    if not runs or not fitz_words:
        out.stats["skipped"] = "no_runs_or_fitz"
        return out

    cmap_f1 = _merged_cmap(pdf_bytes, "F1", fonts)
    y_offset = _calibrate_y_offset(runs, fitz_words)
    out.stats["fitz_y_offset"] = round(y_offset, 3)

    mismatches: list[dict[str, str]] = []
    for row in _label_rows(runs, fitz_words, y_offset):
        label = row["label"]
        content_val = _value_text_content(runs, cmap_f1, row["content_y"])
        fitz_val = _value_text_fitz(fitz_words, row["fitz_y"])
        nc, nf = _norm_text(content_val), _norm_text(fitz_val)
        if not nf:
            continue
        if not nc:
            mismatches.append({
                "label": label,
                "content": content_val,
                "fitz": fitz_val,
            })
            out.flags.append(IntegrityFlag(
                _CODE_PARITY,
                (
                    f"поле «{label}»: decoded content пуст, fitz render «{fitz_val}»"
                ),
                rule_id=RULE_PARITY,
            ))
            continue
        if nc != nf and _NAME_VALUE_RE.match(content_val) and _NAME_VALUE_RE.match(fitz_val):
            mismatches.append({
                "label": label,
                "content": content_val,
                "fitz": fitz_val,
            })
            out.flags.append(IntegrityFlag(
                _CODE_PARITY,
                (
                    f"поле «{label}»: decoded «{content_val}» ≠ fitz «{fitz_val}»"
                ),
                rule_id=RULE_PARITY,
            ))

    out.stats["parity_mismatches"] = mismatches
    return out


def check_tbank_used_glyph_integrity(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> UsedGlyphIntegrityResult:
    out = UsedGlyphIntegrityResult()
    empty = check_used_cid_empty_glyph(pdf_bytes, producer=producer, creator=creator)
    parity = check_text_glyph_parity(pdf_bytes, producer=producer, creator=creator)
    out.flags.extend(empty.flags)
    out.flags.extend(parity.flags)
    out.stats["empty_glyph"] = empty.stats
    out.stats["text_parity"] = parity.stats
    return out
