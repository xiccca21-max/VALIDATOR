"""Sber Jasper glyph spacing vs genuines (ink overlap / wide gaps).

Learned on чеки iText/Jasper «Чек по операции» (n≈59, ~16k letter pairs):
- consecutive non-space CIDs never have overlapping glyf ink (ov_max < 0);
- ink-to-ink gap stays in about 8–599 font units;
- content uses Tj only (no TJ kerning arrays) and never sets Tc≠0;
- /W == floor(hmtx·1000/upem).

SEQ shells that retarget glyphs or botch advances show letters stacked or
stretched — catch that as structure, not FIO morphology.
"""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from io import BytesIO

from ..pdf_forensics import _extract_font_programs, _parse_W_arrays
from ..structure import find_streams, is_content_stream
from .sbp_exact_profile import cids_from_identity_paren
from .types import SberFlag

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover
    TTFont = None

# Space / NBSP-like CID in Sber Identity-H streams.
_SPACE_CID = 3
# Corpus max ink gap between non-space glyphs ≈599; keep slack for new faces.
_INK_GAP_HARD = 650
# sbp_outgoing genuines (n=41): ink_gap_max is exactly 599 (static label pair).
# SEQ font retargets drop it (e.g. 180311 → 329). Floor leaves Jasper slack.
_SBP_OUTGOING_INK_MAX_FLOOR = 550
# sbp_outgoing genuines (n=41): non-space ink_gap_min is one of these exact
# values. Continuous [21,52] let CLEAN 180331/333 through with min=36.
_SBP_OUTGOING_INK_MIN_ALLOWED: frozenset[int] = frozenset({21, 22, 33, 43, 52})
# sber_internal_jasper genuines (n=15): ink_gap_max ∈ {461,561,599}.
# SEQ near-miss internals often land on 462 (absent).
_SBER_INTERNAL_INK_MAX_ALLOWED: frozenset[int] = frozenset({461, 561, 599})
# Any positive ink overlap is absent from genuines.
_INK_OVERLAP_HARD = 0
# sbp_outgoing genuines (n=41): non-space glyph pairs ∈ [238,253].
# CLEAN 180367→135; CLEAN 180379→233 (slipped under old floor 230).
_SBP_OUTGOING_GLYPH_PAIRS_MIN = 238


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, group: str = "B2_layout_content") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier="HARD", group=group, rule_id=code)


def _page_content(pdf_bytes: bytes) -> bytes:
    best = b""
    for raw, dec in find_streams(pdf_bytes or b""):
        if not dec:
            continue
        if is_content_stream(dec) or (b"BT" in dec and b"Tj" in dec):
            if len(dec) > len(best):
                best = dec
    return best


def _font_glyph_meta(pdf_bytes: bytes) -> tuple[dict[int, tuple[int, int, int]], int] | None:
    if TTFont is None:
        return None
    fonts = _extract_font_programs(pdf_bytes) or []
    if not fonts:
        return None
    blob = max(fonts, key=len)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            tt = TTFont(BytesIO(blob))
        except Exception:
            return None
    try:
        upem = int(tt["head"].unitsPerEm) or 1000
        order = tt.getGlyphOrder()
        glyf = tt["glyf"]
    except Exception:
        return None
    meta: dict[int, tuple[int, int, int]] = {}
    for gid, name in enumerate(order):
        try:
            adv, _lsb = tt["hmtx"][name]
            g = glyf[name]
            g.expand(glyf)
            meta[gid] = (int(adv), int(g.xMin), int(g.xMax))
        except Exception:
            continue
    if not meta:
        return None
    return meta, upem


def check_glyph_spacing(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    profile_id: str = "",
) -> CheckResult:
    out = CheckResult()
    if not pdf_bytes:
        return out
    if "iText" not in (producer or "") and b"iText" not in pdf_bytes:
        out.stats["skipped"] = "not_itext"
        return out
    if profile_id and profile_id not in (
        "sbp_outgoing",
        "sbp_request",
        "sber_internal_jasper",
        "",
    ):
        out.stats["skipped"] = "profile"
        return out

    try:
        dec = _page_content(pdf_bytes)
        out.stats["content_len"] = len(dec)
        if not dec:
            return out

        # Emitter invariants: no tracking / TJ kerning on genuines.
        tc_vals = [float(m.group(1)) for m in re.finditer(rb"([\d.\-]+)\s+Tc\b", dec)]
        tw_vals = [float(m.group(1)) for m in re.finditer(rb"([\d.\-]+)\s+Tw\b", dec)]
        tj_arrays = len(re.findall(rb"\]\s*TJ\b", dec))
        out.stats["tc_values"] = tc_vals[:8]
        out.stats["tw_values"] = tw_vals[:8]
        out.stats["tj_array_count"] = tj_arrays
        bad_tc = [v for v in tc_vals if abs(v) > 1e-6]
        bad_tw = [v for v in tw_vals if abs(v) > 1e-6]
        if bad_tc:
            out.flags.append(_f(
                "SBER_CONTENT_TC_TRACKING",
                (
                    f"в /Contents Tc={bad_tc[0]} (не 0); у Jasper/iText "
                    f"межбуквенный tracking не задаётся — чужая/SEQ сериализация"
                ),
            ))
        if bad_tw:
            out.flags.append(_f(
                "SBER_CONTENT_TW_WORD_SPACING",
                (
                    f"в /Contents Tw={bad_tw[0]} (не 0); у Jasper/iText "
                    f"word-spacing оператор не используется"
                ),
            ))
        if tj_arrays:
            out.flags.append(_f(
                "SBER_CONTENT_TJ_KERNING",
                (
                    f"в /Contents {tj_arrays} массив(ов) TJ; корпус Jasper "
                    f"пишет только (…)Tj без кернинг-массивов — пересборка текста"
                ),
            ))

        packed = _font_glyph_meta(pdf_bytes)
        if packed is None:
            out.stats["font_meta"] = "missing"
            return out
        meta, upem = packed
        widths = _parse_W_arrays(pdf_bytes) or {}

        # Pairwise glyf ink: overlap = letters stacked; huge gap = stretched.
        overlaps: list[tuple[int, int, int]] = []
        wide_gaps: list[tuple[int, int, int]] = []
        gap_vals: list[int] = []
        pairs = 0
        used: set[int] = set()
        for m in re.finditer(rb"(\((?:\\.|[^\\)])*\))Tj", dec):
            try:
                cids = cids_from_identity_paren(m.group(1))
            except Exception:
                continue
            used.update(cids)
            for left, right in zip(cids, cids[1:]):
                if left == _SPACE_CID or right == _SPACE_CID:
                    continue
                if left not in meta or right not in meta:
                    continue
                adv1, x_min1, x_max1 = meta[left]
                _adv2, x_min2, x_max2 = meta[right]
                ov = min(x_max1, adv1 + x_max2) - max(x_min1, adv1 + x_min2)
                gap = (adv1 + x_min2) - x_max1
                pairs += 1
                gap_vals.append(gap)
                if ov > _INK_OVERLAP_HARD:
                    overlaps.append((left, right, ov))
                elif gap > _INK_GAP_HARD:
                    wide_gaps.append((left, right, gap))

        # /W ↔ hmtx only for CIDs actually painted (unused template slots can drift).
        w_bad: list[str] = []
        for cid in sorted(used):
            if cid not in widths or cid not in meta:
                continue
            adv = meta[cid][0]
            expected = math.floor(adv * 1000 / upem)
            if int(widths[cid]) != expected:
                w_bad.append(f"CID {cid}: /W={widths[cid]} expected={expected}")
        out.stats["w_quantizer_mismatches"] = len(w_bad)
        if w_bad:
            out.flags.append(_f(
                "SBER_FONT_W_QUANTIZER_MISMATCH",
                f"floor(hmtx*1000/upem) ≠ /W на used CID ({len(w_bad)}): "
                + "; ".join(w_bad[:6]),
                group="font",
            ))

        out.stats["glyph_pairs"] = pairs
        ink_max = max(gap_vals) if gap_vals else None
        if gap_vals:
            out.stats["ink_gap_min"] = min(gap_vals)
            out.stats["ink_gap_max"] = ink_max
        out.stats["ink_overlap_hits"] = len(overlaps)
        out.stats["ink_wide_gap_hits"] = len(wide_gaps)

        ink_min = min(gap_vals) if gap_vals else None

        if (
            profile_id == "sbp_outgoing"
            and pairs
            and pairs < _SBP_OUTGOING_GLYPH_PAIRS_MIN
        ):
            out.flags.append(_f(
                "SBER_GLYPH_PAIRS_TOO_FEW",
                (
                    f"glyph_pairs={pairs} < {_SBP_OUTGOING_GLYPH_PAIRS_MIN} "
                    f"(корпус sbp_outgoing ≥238; n=41) — недособранный "
                    f"content/glyf subset"
                ),
            ))

        # Emitter invariant: static-label pair always produces ~599 u gap.
        if (
            profile_id == "sbp_outgoing"
            and ink_max is not None
            and ink_max < _SBP_OUTGOING_INK_MAX_FLOOR
        ):
            out.flags.append(_f(
                "SBER_GLYPH_INK_MAX_TOO_LOW",
                (
                    f"ink_gap_max={ink_max} u < {_SBP_OUTGOING_INK_MAX_FLOOR} "
                    f"(корпус sbp_outgoing = 599; n=41) — чужие glyph "
                    f"side-bearings / advances в FontFile2"
                ),
            ))

        # Emitter invariant: min non-space ink gap ∈ corpus discrete set.
        if (
            profile_id == "sbp_outgoing"
            and ink_min is not None
            and ink_min not in _SBP_OUTGOING_INK_MIN_ALLOWED
        ):
            allowed = ", ".join(str(v) for v in sorted(_SBP_OUTGOING_INK_MIN_ALLOWED))
            out.flags.append(_f(
                "SBER_GLYPH_INK_MIN_OUT_OF_BAND",
                (
                    f"ink_gap_min={ink_min} u вне корпуса sbp_outgoing "
                    f"({allowed}; n=41) — чужие glyph side-bearings / "
                    f"advances в FontFile2"
                ),
            ))

        if (
            profile_id == "sber_internal_jasper"
            and ink_max is not None
            and ink_max not in _SBER_INTERNAL_INK_MAX_ALLOWED
        ):
            allowed = ", ".join(str(v) for v in sorted(_SBER_INTERNAL_INK_MAX_ALLOWED))
            out.flags.append(_f(
                "SBER_GLYPH_INK_MAX_PROFILE",
                (
                    f"ink_gap_max={ink_max} u вне корпуса sber_internal_jasper "
                    f"({allowed}; n=15) — чужие glyph side-bearings / advances"
                ),
            ))

        if overlaps:
            a, b, ov = overlaps[0]
            out.flags.append(_f(
                "SBER_GLYPH_INK_OVERLAP",
                (
                    f"глифы CID {a}→{b} пересекаются по ink на {ov} u "
                    f"(пар с overlap={len(overlaps)}); в корпусе Jasper "
                    f"межбуквенный ink-overlap = 0 — буквы садятся друг на друга"
                ),
            ))
        if wide_gaps:
            a, b, gap = wide_gaps[0]
            out.flags.append(_f(
                "SBER_GLYPH_INK_WIDE_GAP",
                (
                    f"глифы CID {a}→{b}: ink-gap={gap} u > {_INK_GAP_HARD} "
                    f"(пар={len(wide_gaps)}; корпус ≤599) — слишком большое "
                    f"расстояние между буквами / чужие advances"
                ),
            ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
