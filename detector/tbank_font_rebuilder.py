"""T-Bank font rebuilder hard signature (v5.5 exact case fix).

FAKE only when several independent font-layer contradictions agree:
rebuilt F1/F2 timestamps near PDF CreationDate, PDF FontBBox != TTF head bbox,
and a static reserve of unused digit glyphs in F2.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .ff2_pool import _extract_fontfile2, _font_resources, _obj_spans
from .font_layers import _font_objects, parse_text_runs
from .pdf_forensics import _ttf_tables
from .structure import content_stream_bytes

_MAC_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
_TINKOFF_F1_HEAD_FLAGS = 11
_REBUILD_WINDOW_SEC = 180
_DIGITS = "0123456789"


@dataclass
class RebuilderFlag:
    code: str
    detail: str


@dataclass
class RebuilderResult:
    flags: list[RebuilderFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    is_fake: bool = False


def _mac_ts(head: bytes, offset: int) -> datetime | None:
    if len(head) < offset + 8:
        return None
    sec = struct.unpack(">Q", head[offset:offset + 8])[0]
    if sec > 500_000_000:  # garbage / unset Macintosh timestamps
        return None
    try:
        return _MAC_EPOCH + timedelta(seconds=sec)
    except (OverflowError, ValueError, OSError):
        return None


def _table_bytes(ttf: bytes, tag: bytes) -> bytes | None:
    entry = _ttf_tables(ttf).get(tag)
    if not entry:
        return None
    off, ln = entry
    return ttf[off:off + ln]


def _head_bbox(ttf: bytes) -> tuple[int, int, int, int] | None:
    head = _table_bytes(ttf, b"head")
    if not head or len(head) < 44:
        return None
    return struct.unpack(">hhhh", head[36:44])


def _head_flags(ttf: bytes) -> int | None:
    head = _table_bytes(ttf, b"head")
    if not head or len(head) < 18:
        return None
    return struct.unpack(">H", head[16:18])[0]


def _pdf_creation_dt(pdf_bytes: bytes) -> datetime | None:
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            raw = (doc.metadata or {}).get("creationDate") or ""
            doc.close()
            m = re.match(
                r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})",
                raw.strip(),
            )
            if m:
                y, mo, d, h, mi, s = map(int, m.groups())
                return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        except Exception:
            pass
    m = re.search(
        rb"/CreationDate\s*\(D:(\d{14})",
        pdf_bytes,
    ) or re.search(rb"/CreationDate\s*<D:(\d{14})>", pdf_bytes)
    if not m:
        return None
    raw = m.group(1).decode("ascii", "replace")
    try:
        return datetime(
            int(raw[0:4]), int(raw[4:6]), int(raw[6:8]),
            int(raw[8:10]), int(raw[10:12]), int(raw[12:14]),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _font_descriptor_bbox(
    pdf_bytes: bytes, layer: str,
) -> tuple[int, int, int, int] | None:
    spans = _obj_spans(pdf_bytes)
    num = _font_resources(pdf_bytes).get(layer)
    if not num or num not in spans:
        return None
    blob = spans[num]
    dnum = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
    if dnum:
        blob = spans.get(int(dnum.group(1)), blob)
    fd = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", blob)
    if not fd:
        return None
    fd_blob = spans.get(int(fd.group(1)), b"")
    m = re.search(
        rb"/FontBBox\s*\[\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\]",
        fd_blob,
    )
    if not m:
        return None
    return tuple(int(m.group(i)) for i in range(1, 5))


def _used_cids_by_font(pdf_bytes: bytes) -> dict[str, set[int]]:
    content = content_stream_bytes(pdf_bytes)
    fonts, _ = _font_objects(pdf_bytes)
    widths = {k: v.get("widths", {}) for k, v in fonts.items()}
    used: dict[str, set[int]] = {k: set() for k in ("F1", "F2", "F3")}
    if not content:
        return used
    for run in parse_text_runs(content, widths):
        if run.font in used:
            used[run.font].update(run.cids)
    return used


def _f2_digit_cluster_extras(pdf_bytes: bytes) -> tuple[list[str], list[int]]:
    """Return used digit chars from /W and extra digit-cluster glyph IDs."""
    if not TTFont:
        return [], []
    ttf = _extract_fontfile2(pdf_bytes, "F2")
    if not ttf:
        return [], []
    fonts, _ = _font_objects(pdf_bytes)
    f2 = fonts.get("F2", {})
    widths = set(f2.get("widths") or {})
    cmap = f2.get("cmap") or {}
    used_digits = sorted({
        uchar for cid, uchar in cmap.items()
        if cid in widths and uchar in _DIGITS
    })
    try:
        tt = TTFont(BytesIO(ttf))
        glyf = tt["glyf"]
        order = tt.getGlyphOrder()
    except Exception:
        return used_digits, []

    extras: list[int] = []
    for gid, gname in enumerate(order):
        if gid in widths:
            continue
        try:
            g = glyf[gname]
        except Exception:
            continue
        if g.numberOfContours <= 0:
            continue
        if 300 <= gid <= 320:
            extras.append(gid)
    return used_digits, extras


def _extra_non_component_gids(pdf_bytes: bytes, layer: str) -> list[int]:
    if not TTFont:
        return []
    ttf = _extract_fontfile2(pdf_bytes, layer)
    if not ttf:
        return []
    used = _used_cids_by_font(pdf_bytes).get(layer, set())
    try:
        tt = TTFont(BytesIO(ttf))
        glyf = tt["glyf"]
        order = tt.getGlyphOrder()
    except Exception:
        return []
    extra: list[int] = []
    for cid, gname in enumerate(order):
        if cid == 0 or gname == ".notdef":
            continue
        try:
            g = glyf[gname]
        except Exception:
            continue
        if g.numberOfContours <= 0:
            continue
        if cid not in used:
            extra.append(cid)
    return extra


def _layer_font_profile(pdf_bytes: bytes, layer: str) -> dict:
    ttf = _extract_fontfile2(pdf_bytes, layer)
    if not ttf:
        return {}
    head = _table_bytes(ttf, b"head") or b""
    return {
        "modified": _mac_ts(head, 20),
        "head_flags": _head_flags(ttf),
        "head_bbox": _head_bbox(ttf),
        "pdf_bbox": _font_descriptor_bbox(pdf_bytes, layer),
        "size": len(ttf),
    }


def _bbox_mismatch(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
) -> bool:
    """Missing bbox evidence is inconclusive, not a cross-layer mismatch."""
    return a is not None and b is not None and a != b


def _fonts_rebuilt_at_creation(
    creation: datetime | None,
    f1_mod: datetime | None,
    f2_mod: datetime | None,
) -> bool:
    if not creation or not f1_mod or not f2_mod:
        return False
    if f1_mod.year <= 2022 and f2_mod.year <= 2022:
        return False
    d1 = abs((f1_mod - creation).total_seconds())
    d2 = abs((f2_mod - creation).total_seconds())
    return d1 <= _REBUILD_WINDOW_SEC and d2 <= _REBUILD_WINDOW_SEC


def run_font_rebuilder_check(pdf_bytes: bytes) -> RebuilderResult:
    res = RebuilderResult()
    if not TTFont:
        res.stats["fonttools_missing"] = True
        return res

    creation = _pdf_creation_dt(pdf_bytes)
    f1 = _layer_font_profile(pdf_bytes, "F1")
    f2 = _layer_font_profile(pdf_bytes, "F2")
    res.stats["creation_utc"] = creation.isoformat() if creation else None
    res.stats["F1"] = {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in f1.items()
    }
    res.stats["F2"] = {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in f2.items()
    }

    ts_rebuilt = _fonts_rebuilt_at_creation(
        creation, f1.get("modified"), f2.get("modified"),
    )
    f1_bbox_mismatch = _bbox_mismatch(f1.get("pdf_bbox"), f1.get("head_bbox"))
    f2_bbox_mismatch = _bbox_mismatch(f2.get("pdf_bbox"), f2.get("head_bbox"))
    bbox_mismatch = f1_bbox_mismatch or f2_bbox_mismatch

    used_digits, digit_cluster_extras = _f2_digit_cluster_extras(pdf_bytes)
    res.stats["F2_used_digits"] = used_digits
    res.stats["F2_digit_cluster_extras"] = digit_cluster_extras
    digit_reserve = len(digit_cluster_extras) >= 4

    f1_extra = _extra_non_component_gids(pdf_bytes, "F1")
    f2_extra = _extra_non_component_gids(pdf_bytes, "F2")
    res.stats["F1_extra_gids"] = f1_extra[:12]
    res.stats["F2_extra_gids"] = f2_extra[:12]

    f1_flags = f1.get("head_flags")
    global_tables_foreign = (
        f1_flags is not None and f1_flags != _TINKOFF_F1_HEAD_FLAGS
    )

    if ts_rebuilt:
        res.flags.append(RebuilderFlag(
            "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE",
            "F1/F2 head.modified совпадают со временем генерации PDF "
            f"({f1.get('modified')} / {f2.get('modified')}), "
            "а не с исходными датами TinkoffSans 2021–2022",
        ))

    if bbox_mismatch:
        parts = []
        if f1_bbox_mismatch:
            parts.append(
                f"F1 PDF FontBBox {f1.get('pdf_bbox')} ≠ TTF head {f1.get('head_bbox')}"
            )
        if f2_bbox_mismatch:
            parts.append(
                f"F2 PDF FontBBox {f2.get('pdf_bbox')} ≠ TTF head {f2.get('head_bbox')}"
            )
        res.flags.append(RebuilderFlag(
            "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH",
            "; ".join(parts) + " — на 128 оригиналах таких расхождений нет",
        ))

    if global_tables_foreign:
        res.flags.append(RebuilderFlag(
            "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER",
            f"F1 head.flags={f1_flags}, эталон TinkoffSans={_TINKOFF_F1_HEAD_FLAGS}; "
            "global tables пересчитаны под subset",
        ))

    if digit_reserve:
        res.flags.append(RebuilderFlag(
            "STATIC_EDITABLE_DIGIT_SUBSET_F2",
            f"в F2 используются цифры {used_digits}, "
            f"но в font program заранее встроены неиспользуемые glyph "
            f"{digit_cluster_extras} (FontFile2 {f2.get('size')} B)",
        ))

    if len(f1_extra) >= 4 and len(f2_extra) >= 4 and res.is_fake:
        res.flags.append(RebuilderFlag(
            "EXTRA_UNUSED_GLYPHS_F1_F2",
            f"лишние glyph: F1={len(f1_extra)} шт. {f1_extra[:6]}, "
            f"F2={len(f2_extra)} шт. {f2_extra[:6]}",
        ))

    # v5.5: hard combination — cross-layer font contradictions together.
    res.is_fake = bool(
        bbox_mismatch
        and global_tables_foreign
        and digit_reserve
        and (ts_rebuilt or (f1_bbox_mismatch and f2_bbox_mismatch))
    )
    res.stats["decisive"] = res.is_fake
    return res


def rebuilder_to_log_dict(result: RebuilderResult) -> dict:
    return {
        "is_fake": result.is_fake,
        "flags": [{"code": f.code, "detail": f.detail} for f in result.flags],
        "stats": result.stats,
    }
