"""T-Bank OpenPDF glyph ink spacing (overlap / stacked letters).

Genuine Jasper/OpenPDF TinkoffSans subsets never place consecutive non-space
glyphs with overlapping glyf ink (ink_gap ≥ 0 on n=276 genuines).

SEQ rebuilds that retarget advances/LSB (e.g. «ОЫсмьу» with Ы→с stacked,
ink_gap=−38) show letters sitting on top of each other — structural, not FIO.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from io import BytesIO

from ..structure import find_streams, is_content_stream
from ..tbank_reassembly_family_v3 import resolve_font_graph
from .types import V6Flag

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover
    TTFont = None

_SPACE_CID = 3
# Any negative ink gap = letter overlap. Corpus OpenPDF: 0/276.
_INK_OVERLAP_HARD = 0

_TF_TJ_RE = re.compile(
    rb"/F([123])\s+([\d.]+)\s+Tf|"
    rb"(\((?:\\.|[^\\)])*\))\s*Tj"
)


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _page_content(pdf_bytes: bytes) -> bytes:
    best = b""
    for _raw, dec in find_streams(pdf_bytes or b""):
        if not dec:
            continue
        if is_content_stream(dec) or (b"BT" in dec and b"Tj" in dec):
            if len(dec) > len(best):
                best = dec
    return best


def _unescape_pdf_string(body: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        if body[i] == 0x5C and i + 1 < len(body):
            n = body[i + 1]
            if 48 <= n <= 57:
                j = i + 1
                v = 0
                c = 0
                while j < len(body) and c < 3 and 48 <= body[j] <= 57:
                    v = v * 8 + (body[j] - 48)
                    j += 1
                    c += 1
                out.append(v & 0xFF)
                i = j
                continue
            out.append(n)
            i += 2
            continue
        out.append(body[i])
        i += 1
    return bytes(out)


def _cids_from_paren(literal: bytes) -> list[int]:
    """Identity-H 2-byte CIDs from `(...)` operand."""
    if len(literal) < 2 or literal[0] != 0x28:
        return []
    end = literal.rfind(b")")
    if end <= 0:
        return []
    data = _unescape_pdf_string(literal[1:end])
    if len(data) % 2:
        data += b"\x00"
    return [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]


def _font_meta(ttf: bytes) -> dict[int, tuple[int, int, int]]:
    """gid → (advanceWidth, xMin, xMax) in font units."""
    if TTFont is None or not ttf:
        return {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tt = TTFont(BytesIO(ttf))
        except Exception:
            return {}
    try:
        order = tt.getGlyphOrder()
        glyf = tt["glyf"]
    except Exception:
        return {}
    meta: dict[int, tuple[int, int, int]] = {}
    for gid, name in enumerate(order):
        try:
            adv, _lsb = tt["hmtx"][name]
            g = glyf[name]
            g.expand(glyf)
            meta[gid] = (
                int(adv),
                int(getattr(g, "xMin", 0) or 0),
                int(getattr(g, "xMax", 0) or 0),
            )
        except Exception:
            continue
    return meta


def check_glyph_spacing(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        out.stats["skipped"] = "not_openpdf"
        return out
    if TTFont is None:
        out.stats["skipped"] = "no_fonttools"
        return out

    try:
        graphs = resolve_font_graph(pdf_bytes)
    except Exception:
        out.stats["skipped"] = "font_graph"
        return out

    metas: dict[str, dict[int, tuple[int, int, int]]] = {}
    for role in ("F1", "F2"):
        font = graphs.get(role)
        if not font or not getattr(font, "fontfile2_decoded", None):
            continue
        meta = _font_meta(font.fontfile2_decoded)
        if meta:
            metas[role] = meta
    if not metas:
        out.stats["skipped"] = "no_font_meta"
        return out

    dec = _page_content(pdf_bytes)
    out.stats["content_len"] = len(dec)
    if not dec:
        return out

    font = "F1"
    gaps: list[int] = []
    overlaps: list[tuple[str, int, int, int]] = []
    for m in _TF_TJ_RE.finditer(dec):
        if m.group(1) is not None:
            font = f"F{m.group(1).decode('ascii')}"
            continue
        literal = m.group(3)
        if not literal or font not in metas:
            continue
        meta = metas[font]
        cids = _cids_from_paren(literal)
        for left, right in zip(cids, cids[1:]):
            if left == _SPACE_CID or right == _SPACE_CID:
                continue
            if left not in meta or right not in meta:
                continue
            adv1, _xmin1, xmax1 = meta[left]
            _adv2, xmin2, _xmax2 = meta[right]
            # ink_gap = start of next ink − end of prev ink
            gap = (adv1 + xmin2) - xmax1
            gaps.append(gap)
            if gap < _INK_OVERLAP_HARD:
                overlaps.append((font, left, right, gap))

    out.stats["glyph_pairs"] = len(gaps)
    if gaps:
        out.stats["ink_gap_min"] = min(gaps)
        out.stats["ink_gap_max"] = max(gaps)
    out.stats["ink_overlap_hits"] = len(overlaps)

    if overlaps:
        role, a, b, gap = overlaps[0]
        out.flags.append(V6Flag(
            code="TBANK_GLYPH_INK_OVERLAP",
            detail=(
                f"{role} глифы CID {a}→{b} пересекаются по ink на {gap} u "
                f"(пар с overlap={len(overlaps)}); в корпусе OpenPDF "
                f"межбуквенный ink-overlap = 0 (n=276) — буквы садятся друг "
                f"на друга (как «Ыс» в SEQ-пересборке)"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_GLYPH_INK_OVERLAP",
        ))
    return out
