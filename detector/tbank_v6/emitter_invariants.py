"""Hard Jasper/OpenPDF emitter invariants — not novelty atlases.

Gated by T-Bank SBP Jasper profile. Each check is a serializer/font-assembly
law observed as a singleton on gated genuines (чеки/т банк, n=56), broken by
SEQ reassembly. No visual cues, no donor SHA whitelists.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

from ..tbank_reassembly_family_v3 import (
    profile_gate,
    resolve_font_graph,
)
from .f1_subset_shape import _loca_offsets, _parse_sfnt_tables
from .types import V6Flag

try:
    from ..structure import content_stream_bytes
except Exception:  # pragma: no cover
    content_stream_bytes = None  # type: ignore

_JASPER_TABLE_ORDER = (
    "cvt ",
    "fpgm",
    "glyf",
    "head",
    "hhea",
    "hmtx",
    "loca",
    "maxp",
    "prep",
)

_FORBIDDEN_DESCRIPTOR_KEYS = (
    b"/CIDSet",
    b"/FontMatrix",
    b"/MissingWidth",
    b"/XHeight",
    b"/AvgWidth",
    b"/Leading",
    b"/FontWeight",
)


@dataclass
class EmitterResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _sfnt_table_order(ttf: bytes) -> list[str] | None:
    if not ttf or len(ttf) < 12:
        return None
    n = struct.unpack(">H", ttf[4:6])[0]
    need = 12 + n * 16
    if len(ttf) < need:
        return None
    out: list[str] = []
    for i in range(n):
        tag = ttf[12 + i * 16:12 + i * 16 + 4]
        out.append(tag.decode("latin1", "replace"))
    return out


def _zero_contour_stubs(ttf: bytes) -> list[tuple[int, int]]:
    """GID + span for loca slots with glyf payload but contours==0."""
    try:
        tables = _parse_sfnt_tables(ttf)
        loca = _loca_offsets(tables)
    except Exception:
        return []
    if not loca:
        return []
    offs, _ng = loca
    glyf = tables.get(b"glyf") or b""
    bad: list[tuple[int, int]] = []
    for gid in range(len(offs) - 1):
        a, b = offs[gid], offs[gid + 1]
        if b - a < 2 or b > len(glyf):
            continue
        ncont = struct.unpack(">h", glyf[a:a + 2])[0]
        if ncont == 0:
            bad.append((gid, b - a))
    return bad


def _odd_loca_offsets(ttf: bytes) -> list[int]:
    """Short-format loca stores offsets in words; raw ushorts must be even? No —
    short format values are word offsets; any ushort is valid. We instead flag
    long-format loca with odd *byte* offsets (glyph data must be word-aligned
    per TrueType for long loca)."""
    try:
        tables = _parse_sfnt_tables(ttf)
        head = tables.get(b"head") or b""
        if len(head) < 52:
            return []
        fmt = struct.unpack(">h", head[50:52])[0]
        if fmt == 0:
            return []  # short format: scaled×2 always even
        loca = tables.get(b"loca") or b""
        maxp = tables.get(b"maxp") or b""
        if len(maxp) < 6:
            return []
        ng = struct.unpack(">H", maxp[4:6])[0]
        need = (ng + 1) * 4
        if len(loca) < need:
            return []
        bad: list[int] = []
        for i in range(ng + 1):
            off = struct.unpack(">I", loca[i * 4:i * 4 + 4])[0]
            if off % 2 != 0:
                bad.append(i)
        return bad
    except Exception:
        return []


def _hmtx_cardinality(ttf: bytes) -> tuple[bool, str]:
    """True if hmtx length matches hhea.numberOfHMetrics × maxp.numGlyphs."""
    try:
        tables = _parse_sfnt_tables(ttf)
        maxp = tables.get(b"maxp") or b""
        hhea = tables.get(b"hhea") or b""
        hmtx = tables.get(b"hmtx") or b""
    except Exception:
        return True, "parse_skip"
    if len(maxp) < 6 or len(hhea) < 36 or not hmtx:
        return True, "missing"
    ng = struct.unpack(">H", maxp[4:6])[0]
    nhm = struct.unpack(">H", hhea[34:36])[0]
    if nhm > ng:
        return False, f"numberOfHMetrics={nhm} > numGlyphs={ng}"
    expect = nhm * 4 + (ng - nhm) * 2
    if len(hmtx) != expect:
        return False, (
            f"len(hmtx)={len(hmtx)} ≠ {expect} "
            f"(numGlyphs={ng}, numberOfHMetrics={nhm})"
        )
    return True, f"ok:{len(hmtx)}"


def _composite_empty_components(ttf: bytes) -> list[tuple[int, int]]:
    """(composite_gid, component_gid) where component loca span is empty."""
    try:
        tables = _parse_sfnt_tables(ttf)
        loca = _loca_offsets(tables)
    except Exception:
        return []
    if not loca:
        return []
    offs, _ = loca
    glyf = tables.get(b"glyf") or b""
    bad: list[tuple[int, int]] = []
    for gid in range(len(offs) - 1):
        a, b = offs[gid], offs[gid + 1]
        if b - a < 12 or b > len(glyf):
            continue
        data = glyf[a:b]
        ncont = struct.unpack(">h", data[:2])[0]
        if ncont >= 0:
            continue
        i = 10
        while i + 4 <= len(data):
            flags = struct.unpack(">H", data[i:i + 2])[0]
            cgid = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 4
            if flags & 0x0001:
                i += 4
            else:
                i += 2
            if flags & 0x0008:
                i += 2
            elif flags & 0x0040:
                i += 4
            elif flags & 0x0080:
                i += 8
            if cgid + 1 < len(offs) and offs[cgid] == offs[cgid + 1]:
                bad.append((gid, cgid))
            if not (flags & 0x0020):
                break
    return bad


def _tu_bfchar_count(blob: bytes) -> int:
    return len(re.findall(rb"beginbfchar", blob or b"", flags=re.I))


def check_tbank_emitter_invariants(pdf_bytes: bytes) -> EmitterResult:
    out = EmitterResult()
    gate_ok, gate_stats = profile_gate(pdf_bytes)
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = resolve_font_graph(pdf_bytes)

    # --- FontFile2 structural ---
    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g or not g.fontfile2_decoded:
            continue
        ttf = g.fontfile2_decoded
        order = _sfnt_table_order(ttf)
        out.stats[f"{role}_table_order"] = order
        if order is not None and tuple(order) != _JASPER_TABLE_ORDER:
            out.flags.append(V6Flag(
                code="TBANK_SFNT_TABLE_ORDER_MISMATCH",
                detail=(
                    f"{role} SFNT table order {order} ≠ Jasper "
                    f"{list(_JASPER_TABLE_ORDER)} — чужой subsetter/directory"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_SFNT_TABLE_ORDER_MISMATCH",
            ))

        stubs = _zero_contour_stubs(ttf)
        out.stats[f"{role}_zero_contour_stubs"] = stubs[:16]
        if stubs:
            sample = ", ".join(f"gid{g}@{span}B" for g, span in stubs[:8])
            out.flags.append(V6Flag(
                code="TBANK_GLYF_ZERO_CONTOUR_STUB",
                detail=(
                    f"{role} has {len(stubs)} zero-contour glyf stub(s) "
                    f"({sample}) — loca span>0 but contours=0; Jasper subset "
                    f"never pads ghost slots"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_GLYF_ZERO_CONTOUR_STUB",
            ))

        odd = _odd_loca_offsets(ttf)
        out.stats[f"{role}_odd_loca"] = odd[:16]
        if odd:
            out.flags.append(V6Flag(
                code="TBANK_LOCA_ODD_OFFSET",
                detail=(
                    f"{role} short-loca has odd byte offsets at indices "
                    f"{odd[:12]} — broken short-format loca writer"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_LOCA_ODD_OFFSET",
            ))

        ok_h, detail_h = _hmtx_cardinality(ttf)
        out.stats[f"{role}_hmtx_cardinality"] = detail_h
        if not ok_h:
            out.flags.append(V6Flag(
                code="TBANK_HMTX_METRIC_CARDINALITY",
                detail=(
                    f"{role} hmtx/hhea/maxp cardinality broken: {detail_h}"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_HMTX_METRIC_CARDINALITY",
            ))

        empty_comp = _composite_empty_components(ttf)
        out.stats[f"{role}_composite_empty"] = empty_comp[:16]
        if empty_comp:
            sample = ", ".join(f"{a}→{b}" for a, b in empty_comp[:8])
            out.flags.append(V6Flag(
                code="TBANK_COMPOSITE_EMPTY_COMPONENT",
                detail=(
                    f"{role} composite glyph(s) reference empty component "
                    f"({sample}) — broken glyf transplant/reassembly"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_COMPOSITE_EMPTY_COMPONENT",
            ))

        tu = g.tounicode_decoded or b""
        bf = _tu_bfchar_count(tu)
        out.stats[f"{role}_tu_bfchar"] = bf
        if bf > 0:
            out.flags.append(V6Flag(
                code="TBANK_TOUNICODE_BFCHAR_PRESENT",
                detail=(
                    f"{role} ToUnicode contains beginbfchar×{bf}; Jasper "
                    f"Identity subset emits only beginbfrange — чужой CMap writer"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_TOUNICODE_BFCHAR_PRESENT",
            ))

    # --- PDF descriptor / content serializer ---
    hits = [k.decode() for k in _FORBIDDEN_DESCRIPTOR_KEYS if k in pdf_bytes]
    out.stats["forbidden_descriptor_keys"] = hits
    if hits:
        out.flags.append(V6Flag(
            code="TBANK_FORBIDDEN_FONT_DESCRIPTOR_KEY",
            detail=(
                f"PDF contains forbidden FontDescriptor/font keys {hits}; "
                f"Jasper IB Receipt never emits CIDSet/FontMatrix/MissingWidth/"
                f"XHeight/AvgWidth/Leading/FontWeight"
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_FORBIDDEN_FONT_DESCRIPTOR_KEY",
        ))

    if b"/ProcSet" in pdf_bytes:
        out.flags.append(V6Flag(
            code="TBANK_PROCSET_PRESENT",
            detail=(
                "PDF contains /ProcSet; Jasper/OpenPDF IB Receipt omits ProcSet "
                "— legacy/foreign serializer"
            ),
            tier="A",
            group="B1_serializer_container",
            rule_id="TBANK_PROCSET_PRESENT",
        ))

    if b"/Predictor" in pdf_bytes:
        out.flags.append(V6Flag(
            code="TBANK_FLATE_PREDICTOR_PRESENT",
            detail=(
                "PDF contains /Predictor on a stream; Jasper IB Receipt uses "
                "raw Flate without predictor"
            ),
            tier="A",
            group="B1_serializer_container",
            rule_id="TBANK_FLATE_PREDICTOR_PRESENT",
        ))

    if re.search(rb"stream\r\n", pdf_bytes):
        n = len(re.findall(rb"stream\r\n", pdf_bytes))
        out.flags.append(V6Flag(
            code="TBANK_STREAM_CRLF_EOL",
            detail=(
                f"PDF has {n} stream\\r\\n EOL(s); Jasper/OpenPDF emits only "
                f"stream\\n — чужой byte-level serializer"
            ),
            tier="A",
            group="B1_serializer_container",
            rule_id="TBANK_STREAM_CRLF_EOL",
        ))

    cs = b""
    if content_stream_bytes is not None:
        try:
            cs = content_stream_bytes(pdf_bytes) or b""
        except Exception:
            cs = b""
    out.stats["content_len"] = len(cs)
    if cs:
        if re.search(rb"\bTJ\b", cs):
            out.flags.append(V6Flag(
                code="TBANK_CONTENT_TJ_PRESENT",
                detail=(
                    "page /Contents uses TJ operator; Jasper IB Receipt emits "
                    "only Tj — array-showText from foreign layout engine"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_CONTENT_TJ_PRESENT",
            ))
        marked = len(re.findall(rb"\b(?:BMC|BDC|EMC)\b", cs))
        if marked:
            out.flags.append(V6Flag(
                code="TBANK_MARKED_CONTENT_PRESENT",
                detail=(
                    f"page /Contents has {marked} marked-content op(s) "
                    f"(BMC/BDC/EMC); Jasper IB Receipt has none"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_MARKED_CONTENT_PRESENT",
            ))
        # nested BT
        depth = 0
        nest_bad = 0
        for op in re.findall(rb"\b(BT|ET)\b", cs):
            if op == b"BT":
                depth += 1
                if depth > 1:
                    nest_bad += 1
            else:
                depth -= 1
                if depth < 0:
                    nest_bad += 1
                    depth = 0
        out.stats["bt_nest_violations"] = nest_bad
        if nest_bad:
            out.flags.append(V6Flag(
                code="TBANK_BT_NESTING_VIOLATION",
                detail=(
                    f"BT/ET nesting violations×{nest_bad} (depth>1 or "
                    f"unbalanced); Jasper emits flat BT…ET only"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_BT_NESTING_VIOLATION",
            ))

    return out
