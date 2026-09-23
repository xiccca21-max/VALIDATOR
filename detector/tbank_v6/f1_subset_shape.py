"""F1 subset shape invariants (composite floor + glyf↔cmap envelope).

Genuine Jasper/OpenPDF TinkoffSans-Regular subsets keep a stable relationship
between ToUnicode cardinality and glyf table bytes, and card shells always
embed ≥10 composite glyphs (template КОСаеорсу + ≥1 name composite).

SEQ rebuilds that pad/strip outlines while keeping FontFile2 decoded size
inside the coarse envelope still break these shape invariants.

Genuine subsets also write glyf exactly to loca[-1]; SEQ often leaves
non-zero trailing junk after the last glyph offset (same length as a twin
corpus glyf, different bytes).

Glyf↔cmap OUTLIER is HARD only for far transplants (~400 B beyond the
sampled cmap bucket). Per-cmap min–max itself is a novelty atlas.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field

from .ff2_sha_atlas import FF2_SHA_BY_HEIGHT_CMAP_GLYF
from .twin_shape_atlas import TWIN_SHAPE_BY_HEIGHT_CMAP_GLYF
from .types import V6Flag

# Exact F1 glyf lengths per (MediaBox height, ToUnicode cardinality).
# SEQ rebuilds often sit inside min–max envelopes but miss every corpus value
# (SBP/card/«Клиенту»). New genuine sizes → atlas update (same ops as cmap unknown).
# Values: cmap → (exact frozenset, n_atlas).
_GLYF_EXACT_BY_HEIGHT_CMAP: dict[int, dict[int, tuple[frozenset[int], int]]] = {
    411: {
        57: (frozenset({10_700, 10_784, 10_804}), 6),
        58: (frozenset({10_898, 10_932, 10_958}), 6),
        59: (frozenset({11_024, 11_108, 11_230}), 8),
        60: (frozenset({11_674}), 2),
    },
    431: {
        57: (frozenset({10_918}), 4),
        58: (frozenset({11_174}), 2),
        59: (frozenset({
            10_908, 10_970, 11_006, 11_008, 11_020, 11_070, 11_080,
            11_128, 11_162, 11_198, 11_348,
        }), 26),
        60: (frozenset({
            11_068, 11_204, 11_280, 11_282, 11_314, 11_360, 11_378, 11_412,
        }), 16),
        61: (frozenset({
            11_126, 11_198, 11_266, 11_388, 11_408, 11_416, 11_460, 11_524, 11_628,
        }), 20),
        62: (frozenset({11_398, 11_568, 11_656}), 6),
        63: (frozenset({11_610, 11_776, 11_878}), 6),
    },
    451: {
        61: (frozenset({11_332}), 2),
        62: (frozenset({11_366, 11_516, 11_538, 11_576, 11_626}), 12),
        63: (frozenset({11_716}), 2),
        64: (frozenset({11_868, 11_946}), 4),
        65: (frozenset({12_430}), 4),
    },
    471: {
        59: (frozenset({11_088, 11_102}), 4),
        60: (frozenset({11_142}), 2),
        61: (frozenset({11_614, 11_620}), 4),
        62: (frozenset({11_302, 11_342}), 4),
        63: (frozenset({11_732}), 2),
    },
    519: {
        65: (frozenset({12_170}), 2),
        66: (frozenset({12_080, 12_178, 12_308, 12_344}), 7),
        67: (frozenset({
            12_176, 12_296, 12_344, 12_422, 12_482, 12_530, 12_560, 12_592, 12_978,
        }), 27),
        68: (frozenset({
            12_296, 12_374, 12_398, 12_434, 12_468, 12_528, 12_554, 12_560,
            12_596, 12_598, 12_626, 12_700, 12_784, 13_002,
        }), 27),
        69: (frozenset({12_520, 12_684, 12_720, 12_768, 12_784, 12_816}), 16),
        70: (frozenset({13_000, 13_210}), 4),
        71: (frozenset({12_818, 12_852, 12_880, 12_910, 13_002}), 14),
        72: (frozenset({12_612}), 2),
        74: (frozenset({13_738}), 1),
        75: (frozenset({13_610}), 6),
        76: (frozenset({13_794, 14_032}), 4),
    },
    539: {
        66: (frozenset({12_328}), 4),
        67: (frozenset({12_328, 12_442}), 4),
        68: (frozenset({12_864, 13_038}), 4),
        69: (frozenset({12_236}), 2),
        73: (frozenset({13_264}), 2),
    },
}
_MIN_GLYF_EXACT_N = 1

# MediaBox height → cmap_cardinality → (glyf_lo, glyf_hi, n_atlas)
# From чеки OpenPDF genuines. Buckets with n≥4.
_GLYF_BY_HEIGHT_CMAP: dict[int, dict[int, tuple[int, int, int]]] = {
    411: {
        57: (10_700, 10_804, 6),
        58: (10_898, 10_958, 6),
        59: (11_024, 11_230, 8),
        60: (11_674, 11_674, 2),
    },
    431: {
        57: (10_918, 10_918, 4),
        58: (11_174, 11_174, 2),
        59: (10_908, 11_348, 26),
        60: (11_068, 11_412, 16),
        61: (11_126, 11_628, 20),
        62: (11_398, 11_656, 6),
        63: (11_610, 11_878, 6),
    },
    451: {
        62: (11_366, 11_626, 12),
        64: (11_868, 11_946, 4),
        65: (12_430, 12_430, 4),
    },
    471: {
        59: (11_088, 11_102, 4),
        # n=2 zero-span: all genuines share identical glyf for this cmap
        60: (11_142, 11_142, 2),
        61: (11_614, 11_620, 4),
        62: (11_302, 11_342, 4),
        63: (11_732, 11_732, 2),
    },
    519: {
        65: (12_170, 12_170, 2),
        66: (12_080, 12_344, 7),
        67: (12_176, 12_978, 27),
        68: (12_296, 13_002, 27),
        69: (12_520, 12_816, 16),
        70: (13_000, 13_210, 4),
        71: (12_818, 13_002, 14),
        72: (12_612, 12_612, 2),
        74: (13_738, 13_738, 1),
        75: (13_610, 13_610, 6),
        76: (13_794, 14_032, 4),
    },
    539: {
        66: (12_328, 12_328, 4),
        67: (12_328, 12_442, 4),
        68: (12_864, 13_038, 4),
        69: (12_236, 12_236, 2),
        73: (13_264, 13_264, 2),
    },
}

# Observed F1 ToUnicode cardinalities per MediaBox height (any n≥1).
# SEQ SBP CLEAN cluster on cmap=73 @519 — absent from genuines (n=110).
_CMAP_SEEN_BY_HEIGHT: dict[int, frozenset[int]] = {
    411: frozenset({57, 58, 59, 60}),
    431: frozenset({57, 58, 59, 60, 61, 62, 63}),
    451: frozenset({61, 62, 63, 64, 65}),
    471: frozenset({59, 60, 61, 62, 63}),
    519: frozenset({65, 66, 67, 68, 69, 70, 71, 72, 74, 75, 76}),
    539: frozenset({66, 67, 68, 69, 73}),
}
_CMAP_HEIGHT_N: dict[int, int] = {
    411: 22, 431: 80, 451: 24, 471: 16, 519: 110, 539: 16,
}

# Card OpenPDF h=471: genuines n=14 all have ≥10 F1 composites.
_CARD_COMPOSITE_FLOOR = 10
_CARD_COMPOSITE_HEIGHT = 471
_GLYF_SLACK = 400
_MIN_ATLAS = 4
# Zero-span buckets (lo==hi) are deterministic subset sizes — allow n≥2.
_MIN_ATLAS_ZERO_SPAN = 2
_MIN_HEIGHT_N_FOR_CMAP = 20


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _mediabox_height(pdf_bytes: bytes) -> int | None:
    m = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]",
        pdf_bytes or b"",
    )
    if not m:
        return None
    try:
        return int(round(float(m.group(4))))
    except ValueError:
        return None


def _pdf_text(pdf_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _parse_sfnt_tables(ttf: bytes) -> dict[bytes, bytes]:
    if len(ttf) < 12:
        return {}
    n_tables = struct.unpack(">H", ttf[4:6])[0]
    out: dict[bytes, bytes] = {}
    for i in range(n_tables):
        off = 12 + i * 16
        if off + 16 > len(ttf):
            break
        tag = ttf[off:off + 4]
        toff, tlen = struct.unpack(">II", ttf[off + 8:off + 16])
        if toff + tlen <= len(ttf):
            out[tag] = ttf[toff:toff + tlen]
    return out


def _loca_offsets(tables: dict[bytes, bytes]) -> tuple[list[int], int] | None:
    head = tables.get(b"head")
    maxp = tables.get(b"maxp")
    loca = tables.get(b"loca")
    if not head or not maxp or not loca or len(head) < 52 or len(maxp) < 6:
        return None
    index_to_loc = struct.unpack(">H", head[50:52])[0]
    num_glyphs = struct.unpack(">H", maxp[4:6])[0]
    if index_to_loc == 0:
        if len(loca) < (num_glyphs + 1) * 2:
            return None
        offsets = [struct.unpack(">H", loca[i:i + 2])[0] * 2 for i in range(0, (num_glyphs + 1) * 2, 2)]
    else:
        if len(loca) < (num_glyphs + 1) * 4:
            return None
        offsets = [struct.unpack(">I", loca[i:i + 4])[0] for i in range(0, (num_glyphs + 1) * 4, 4)]
    return offsets, num_glyphs


def _parse_tounicode_cids(data: bytes) -> set[int]:
    cids: set[int] = set()
    for m in re.finditer(rb"beginbfchar\s*(.*?)\s*endbfchar", data, re.S | re.I):
        for sm in re.finditer(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1)):
            cids.add(int(sm.group(1), 16))
    for m in re.finditer(rb"beginbfrange\s*(.*?)\s*endbfrange", data, re.S | re.I):
        for sm in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(?:<([0-9A-Fa-f]+)>|\[)",
            m.group(1),
        ):
            lo = int(sm.group(1), 16)
            hi = int(sm.group(2), 16)
            cids.update(range(lo, hi + 1))
    return cids


def _f1_fontfile2_and_tounicode(pdf_bytes: bytes) -> tuple[bytes | None, bytes | None]:
    """Best-effort F1 FontFile2 decoded + ToUnicode decoded via name /F1."""
    # Prefer object graph via resolve if available — keep this module light:
    # find first FontFile2 belonging to TinkoffSans-Regular descriptor near F1.
    try:
        from detector.tbank_reassembly_family_v3 import resolve_font_graph
        g = resolve_font_graph(pdf_bytes).get("F1")
        if g and g.fontfile2_decoded:
            tu = g.tounicode_decoded if getattr(g, "tounicode_decoded", None) else None
            return g.fontfile2_decoded, tu
    except Exception:
        pass
    return None, None


def _f1_shape(pdf_bytes: bytes) -> dict | None:
    ttf, tu = _f1_fontfile2_and_tounicode(pdf_bytes)
    if not ttf:
        return None
    tables = _parse_sfnt_tables(ttf)
    glyf = tables.get(b"glyf")
    loca_parsed = _loca_offsets(tables)
    if glyf is None or not loca_parsed:
        return None
    offsets, num_glyphs = loca_parsed
    simple = comp = 0
    for gid in range(num_glyphs):
        if gid + 1 >= len(offsets) or offsets[gid + 1] <= offsets[gid]:
            continue
        start, end = offsets[gid], offsets[gid + 1]
        if end > len(glyf) or start >= end:
            continue
        data = glyf[start:end]
        if len(data) < 2:
            continue
        ncont = struct.unpack(">h", data[:2])[0]
        if ncont < 0:
            comp += 1
        elif ncont > 0:
            simple += 1
    cmap_n = 0
    if tu:
        cmap_n = len(_parse_tounicode_cids(tu))
    else:
        try:
            from detector.tbank_reassembly_family_v3 import resolve_font_graph
            g = resolve_font_graph(pdf_bytes).get("F1")
            if g and g.tounicode:
                cmap_n = len(g.tounicode)
        except Exception:
            pass
    return {
        "glyf_len": len(glyf),
        "cmap_n": cmap_n,
        "composite_n": comp,
        "simple_n": simple,
        "nonempty_n": simple + comp,
        "ff2_decoded": len(ttf),
    }


def _glyf_trailing_after_loca(ttf: bytes) -> tuple[int, int, bool] | None:
    """Return (glyf_len, loca_end, trail_all_zero) or None if unparsable."""
    tables = _parse_sfnt_tables(ttf)
    glyf = tables.get(b"glyf") or b""
    loca = _loca_offsets(tables)
    if not loca or not glyf:
        return None
    offsets, _ng = loca
    loca_end = int(offsets[-1]) if offsets else 0
    if loca_end < 0 or loca_end > len(glyf):
        return None
    trail = glyf[loca_end:]
    return len(glyf), loca_end, (not trail) or all(b == 0 for b in trail)


def check_f1_subset_shape(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        return out
    height = _mediabox_height(pdf_bytes)
    shape = _f1_shape(pdf_bytes)
    out.stats["mediabox_height"] = height
    if shape:
        out.stats.update(shape)
    if height is None or not shape:
        return out

    text = _pdf_text(pdf_bytes)
    is_card = "Карта получателя" in text or "По номеру карты" in text
    is_sbp = "Идентификатор операции" in text
    out.stats["channel_hint"] = "card" if is_card else ("sbp" if is_sbp else "")

    # --- glyf trailing junk past loca[-1] (SEQ residual; genuines pad=0) ---
    ff2, _tu = _f1_fontfile2_and_tounicode(pdf_bytes)
    if ff2:
        trail_info = _glyf_trailing_after_loca(ff2)
        if trail_info is not None:
            glyf_len, loca_end, trail_zero = trail_info
            pad = glyf_len - loca_end
            out.stats["glyf_loca_trail"] = {
                "glyf_len": glyf_len,
                "loca_end": loca_end,
                "pad": pad,
                "trail_zero": trail_zero,
            }
            if pad > 0:
                out.flags.append(V6Flag(
                    code="TBANK_F1_GLYF_TRAILING_JUNK",
                    detail=(
                        f"F1 glyf={glyf_len} B > loca_end={loca_end} "
                        f"(pad={pad}, trail_zero={trail_zero}) — "
                        f"лишние байты после последнего глифа; корпус OpenPDF "
                        f"пишет glyf ровно по loca (pad=0, n=270) — "
                        f"след SEQ-пересборки subset"
                    ),
                    tier="A",
                    group="B5_font_rebuilder",
                    rule_id="TBANK_F1_GLYF_TRAILING_JUNK",
                ))

        # Exact (height,cmap,glyf) twin with foreign FontFile2 bytes.
        # Demoted from HARD (novelty sha); keep stats for telemetry.
        key = (height, shape["cmap_n"], shape["glyf_len"])
        allowed_sha = FF2_SHA_BY_HEIGHT_CMAP_GLYF.get(key)
        if allowed_sha is not None and shape["cmap_n"] > 0:
            sha16 = hashlib.sha256(ff2).hexdigest()[:16]
            out.stats["ff2_sha_twin"] = {
                "key": key,
                "sha16": sha16,
                "allowed_n": len(allowed_sha),
                "mismatch": sha16 not in allowed_sha,
            }

        # Twin shape: same (h,cmap,glyf) ⇒ unique (composite,nonempty,simple)
        # in genuines (0 conflicts / 120 twins). SEQ copies glyf length with
        # foreign glyph mix (round8_07 vs round2_02).
        expected_shape = TWIN_SHAPE_BY_HEIGHT_CMAP_GLYF.get(key)
        if expected_shape is not None and shape["cmap_n"] > 0:
            got = (
                int(shape["composite_n"]),
                int(shape["nonempty_n"]),
                int(shape["simple_n"]),
            )
            out.stats["twin_shape"] = {
                "key": key,
                "expected": expected_shape,
                "got": got,
            }
            if got != expected_shape:
                out.flags.append(V6Flag(
                    code="TBANK_F1_TWIN_SHAPE_MISMATCH",
                    detail=(
                        f"F1 twin height={height} cmap={shape['cmap_n']} "
                        f"glyf={shape['glyf_len']}: shape "
                        f"composite/nonempty/simple={got} ≠ корпус "
                        f"{expected_shape} — длина glyf как у донора, "
                        f"состав glyph'ов чужой (SEQ)"
                    ),
                    tier="A",
                    group="B5_font_rebuilder",
                    rule_id="TBANK_F1_TWIN_SHAPE_MISMATCH",
                ))

    # --- Card composite floor ---
    if (
        is_card
        and height == _CARD_COMPOSITE_HEIGHT
        and shape["composite_n"] < _CARD_COMPOSITE_FLOOR
    ):
        out.flags.append(V6Flag(
            code="TBANK_F1_COMPOSITE_FLOOR",
            detail=(
                f"F1 composite glyphs={shape['composite_n']} < {_CARD_COMPOSITE_FLOOR} "
                f"для card height={height} (корпус OpenPDF ≥{_CARD_COMPOSITE_FLOOR}, "
                f"n=14) — subset без name-composite, типичный SEQ residual"
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_F1_COMPOSITE_FLOOR",
        ))

    # Card-to-Sber (height 471): live receipts have no drawn glyphs outside
    # the characters on the page and their composite parts. 7/7 genuines.
    if is_card and height == _CARD_COMPOSITE_HEIGHT and ff2:
        try:
            from detector.tbank_reassembly_family_v3 import (
                _composite_closure,
                _nonempty_gids,
                extract_used_cids,
                resolve_font_graph,
            )
            graphs = resolve_font_graph(pdf_bytes)
            used = extract_used_cids(pdf_bytes)
            g1 = graphs.get("F1")
            if g1 and g1.fontfile2_decoded:
                seeds = set(g1.tounicode) | used.get("F1", set())
                unused = sorted(
                    _nonempty_gids(g1.fontfile2_decoded) - _composite_closure(
                        g1.fontfile2_decoded, seeds,
                    ) - {0}
                )
                out.stats["f1_card_unused_drawings"] = unused
                if unused:
                    out.flags.append(V6Flag(
                        code="TBANK_F1_CARD_UNUSED_DRAWING",
                        detail=(
                            f"F1 height=471: нарисованы буквы, которых нет на странице "
                            f"и которые не входят в составные знаки: {unused[:12]}. "
                            f"У живых переводов на карту Сбера таких рисунков нет (7/7)"
                        ),
                        tier="A",
                        group="B5_font_rebuilder",
                        rule_id="TBANK_F1_CARD_UNUSED_DRAWING",
                    ))
        except Exception:
            out.stats["f1_card_unused_drawings"] = "error"

    # --- unknown cmap cardinality: SBP only (h=519, n=110) ---
    seen = _CMAP_SEEN_BY_HEIGHT.get(height)
    height_n = _CMAP_HEIGHT_N.get(height, 0)
    out.stats["cmap_seen_atlas"] = {
        "height_n": height_n,
        "allowed_n": len(seen) if seen else 0,
        "cmap": shape["cmap_n"],
    }
    if (
        height == 519
        and seen is not None
        and height_n >= _MIN_HEIGHT_N_FOR_CMAP
        and shape["cmap_n"] > 0
        and shape["cmap_n"] not in seen
    ):
        out.flags.append(V6Flag(
            code="TBANK_F1_CMAP_CARDINALITY_UNKNOWN",
            detail=(
                f"F1 ToUnicode cmap={shape['cmap_n']} вне корпуса height={height} "
                f"(известны {sorted(seen)}, n={height_n}) — чужой subset cardinality / "
                f"SEQ-пересборка"
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_F1_CMAP_CARDINALITY_UNKNOWN",
        ))

    # --- glyf↔cmap envelope (all heights with atlas n≥min) ---
    # Exact allowlist stays diagnostic/IGNORED (finite whitelist novelty).
    # HARD only for far transplants: SEQ card sits ~600 B outside the cmap
    # bucket (h=471 cmap=62 glyf=11948 vs 11302–11342). Genuine names can
    # overshoot the sampled max by ~100–200 B (Receipt 13: 12950 vs 12816).
    buckets = _GLYF_BY_HEIGHT_CMAP.get(height) or {}
    env = buckets.get(shape["cmap_n"]) if shape["cmap_n"] > 0 else None
    if env:
        lo, hi, n_atlas = env
        out.stats["glyf_cmap_atlas"] = {
            "cmap": shape["cmap_n"], "lo": lo, "hi": hi, "n_atlas": n_atlas,
        }
        zero_span = lo == hi
        min_n = _MIN_ATLAS_ZERO_SPAN if zero_span else _MIN_ATLAS
        if n_atlas >= min_n:
            hard_lo, hard_hi = lo - _GLYF_SLACK, hi + _GLYF_SLACK
            glyf = shape["glyf_len"]
            if glyf < hard_lo or glyf > hard_hi:
                side = "больше" if glyf > hard_hi else "меньше"
                out.flags.append(V6Flag(
                    code="TBANK_F1_GLYF_CMAP_OUTLIER",
                    detail=(
                        f"F1 glyf={glyf} B при cmap={shape['cmap_n']} — {side} корпуса "
                        f"height={height} (atlas {lo}–{hi}, n={n_atlas}; "
                        f"band {hard_lo}–{hard_hi}) — чужой subset shape / пересборка"
                    ),
                    tier="A",
                    group="B5_font_rebuilder",
                    rule_id="TBANK_F1_GLYF_CMAP_OUTLIER",
                ))

    # Exact glyf allowlist: keep stats for telemetry; flag remains IGNORED.
    exact_buckets = _GLYF_EXACT_BY_HEIGHT_CMAP.get(height) or {}
    exact_entry = exact_buckets.get(shape["cmap_n"]) if shape["cmap_n"] > 0 else None
    if exact_entry is not None:
        exact, exact_n = exact_entry
        out.stats["glyf_exact_atlas"] = {
            "cmap": shape["cmap_n"],
            "glyf": shape["glyf_len"],
            "n_atlas": exact_n,
            "allowed": sorted(exact),
        }
        if exact_n >= _MIN_GLYF_EXACT_N and shape["glyf_len"] not in exact:
            out.flags.append(V6Flag(
                code="TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN",
                detail=(
                    f"F1 glyf={shape['glyf_len']} B при cmap={shape['cmap_n']} "
                    f"вне точного корпуса height={height} "
                    f"(allowed={sorted(exact)}, n={exact_n}) — SEQ subset в зазоре "
                    f"envelope, не банковская комбинация jasper/OpenPDF"
                ),
                tier="A",
                group="B5_font_rebuilder",
                rule_id="TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN",
            ))
    return out
