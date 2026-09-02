# -*- coding: utf-8 -*-
"""F2 (TinkoffSans-Medium) glyf length checks.

1) Height×glyf exact whitelist — diagnostic/IGNORE only (novelty atlas).
2) F1 nonempty-hmtx → F2 glyf co-generation — IGNORE. Known F1 kits pair with
   new genuine Medium lengths (Receipt 15: hmtx 23b7d7… expected 856, got 1044).
3) Height-451 midgap — HARD only when the F2.glyf length is also absent from
   the global genuine union (SEQ phone 1130; 1144 is native Medium elsewhere).
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field
from io import BytesIO

from .f1_f2_hmtx_cogen_atlas import _F1_HMTX_TO_F2_GLYF
from .types import V6Flag

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

# Exact F2 glyf table lengths by MediaBox height (чеки/т банк OpenPDF, n=128).
# Kept for telemetry / IGNORE flag only — not a HARD gate.
_F2_GLYF_EXACT_BY_HEIGHT: dict[int, tuple[frozenset[int], int]] = {
    411: (frozenset({866, 992, 1008, 1094, 1226, 1322}), 11),
    431: (frozenset({
        866, 904, 974, 992, 1012, 1096, 1144, 1214, 1226, 1228, 1242, 1248,
        1260, 1264, 1282, 1322, 1506, 1530, 1680,
    }), 40),
    451: (frozenset({866, 992, 1008, 1096, 1106, 1144, 1226, 1232}), 12),
    471: (frozenset({856, 992, 1094, 1096, 1232, 1720, 1932}), 8),
    519: (frozenset({
        812, 822, 856, 904, 934, 954, 988, 992, 1008, 1012, 1046, 1062, 1094,
        1096, 1100, 1106, 1134, 1144, 1212, 1228, 1232, 1246, 1260, 1284, 1320,
        1374, 1454, 1472, 1554, 1636,
    }), 48),
    539: (frozenset({904, 954, 974, 1062, 1144, 1232}), 8),
}
_MIN_ATLAS = 8

# F2.glyf lengths seen on any genuine OpenPDF height. Height-451 "holes"
# between sampled sizes are not empty: 1144 is native Medium at 431/519/539
# (Receipt 11). SEQ phone 1130 is not in this union.
_F2_GLYF_ANY_HEIGHT: frozenset[int] = frozenset(
    size for sizes, _n in _F2_GLYF_EXACT_BY_HEIGHT.values() for size in sizes
)


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


def _font_graph_ff2(pdf_bytes: bytes, role: str) -> bytes | None:
    try:
        from detector.tbank_reassembly_family_v3 import resolve_font_graph

        g = resolve_font_graph(pdf_bytes)
        fr = g.get(role)
        if fr and fr.fontfile2_decoded:
            return fr.fontfile2_decoded
    except Exception:
        pass
    return None


def _glyf_len(ttf: bytes) -> int | None:
    if not ttf or len(ttf) < 12:
        return None
    if TTFont is not None:
        try:
            tt = TTFont(BytesIO(ttf))
            if "glyf" not in tt:
                return None
            n = len(tt.getTableData("glyf"))
            tt.close()
            return int(n)
        except Exception:
            pass
    n_tables = struct.unpack(">H", ttf[4:6])[0]
    for i in range(n_tables):
        off = 12 + i * 16
        if off + 16 > len(ttf):
            break
        tag = ttf[off : off + 4]
        toff, tlen = struct.unpack(">II", ttf[off + 8 : off + 16])
        if tag == b"glyf" and toff + tlen <= len(ttf):
            return int(tlen)
    return None


def _f1_nonempty_hmtx_sha16(ttf: bytes) -> str | None:
    """Anonymous multiset of hmtx advances for nonempty glyphs (sha16)."""
    if not ttf or TTFont is None:
        return None
    try:
        tt = TTFont(BytesIO(ttf))
        if "loca" not in tt or "hmtx" not in tt:
            tt.close()
            return None
        loca = list(tt["loca"])
        advs = sorted(
            int(tt["hmtx"].metrics[name][0])
            for i, name in enumerate(tt.getGlyphOrder())
            if int(loca[i + 1]) > int(loca[i])
        )
        tt.close()
        return hashlib.sha256(",".join(map(str, advs)).encode()).hexdigest()[:16]
    except Exception:
        return None


def check_f2_subset_shape(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        out.stats["skipped"] = "not_openpdf"
        return out
    height = _mediabox_height(pdf_bytes)
    out.stats["mediabox_height"] = height

    f2 = _font_graph_ff2(pdf_bytes, "F2")
    if not f2:
        out.stats["skipped"] = "no_f2"
        return out
    glyf = _glyf_len(f2)
    out.stats["f2_glyf_len"] = glyf
    out.stats["f2_ff2_decoded"] = len(f2)
    if glyf is None:
        return out

    # --- F1 hmtx ↔ F2 glyf co-generation (HARD) ---
    f1 = _font_graph_ff2(pdf_bytes, "F1")
    hmtx_sha = _f1_nonempty_hmtx_sha16(f1) if f1 else None
    out.stats["f1_hmtx_sha16"] = hmtx_sha
    if hmtx_sha:
        allowed_f2 = _F1_HMTX_TO_F2_GLYF.get(hmtx_sha)
        out.stats["f1_hmtx_f2_cogen"] = {
            "hmtx_sha16": hmtx_sha,
            "f2_glyf": glyf,
            "allowed": sorted(allowed_f2) if allowed_f2 is not None else None,
            "atlas_n": len(_F1_HMTX_TO_F2_GLYF),
        }
        if allowed_f2 is not None and glyf not in allowed_f2:
            out.flags.append(V6Flag(
                code="TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH",
                detail=(
                    f"F1 nonempty-hmtx sha16={hmtx_sha} в корпусе парный с "
                    f"F2.glyf∈{sorted(allowed_f2)}, получено F2.glyf={glyf} — "
                    f"Medium subset с чужого kit при том же Regular metric "
                    f"fingerprint (SEQ F1/F2 co-generation break) "
                    f"(IGNORED: known F1 kit can pair with a new genuine Medium)"
                ),
                tier="IGNORE",
                group="B5_font_rebuilder",
                rule_id="TBANK_F1_HMTX_F2_GLYF_COGEN_MISMATCH",
            ))

    # Height 451 sampled F2.glyf skipped 1106→1226, but 1144 is a native
    # Medium size on other heights. Only HARD if the length is also absent
    # from the global genuine union (SEQ phone 1130; not Receipt 11 / 1144).
    if (
        height == 451
        and glyf is not None
        and 1106 < glyf < 1226
        and glyf not in _F2_GLYF_ANY_HEIGHT
    ):
        out.flags.append(V6Flag(
            code="TBANK_F2_GLYF_HEIGHT_MIDGAP",
            detail=(
                f"F2 glyf={glyf} B — в зазоре height=451 между Medium 1106 и "
                f"1226 и нет ни на одном genuine height (SEQ phone 1130)"
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_F2_GLYF_HEIGHT_MIDGAP",
        ))

    # --- Height exact whitelist (IGNORE / novelty) ---
    if height is None:
        return out
    entry = _F2_GLYF_EXACT_BY_HEIGHT.get(height)
    if entry is None:
        return out
    allowed, n_atlas = entry
    out.stats["f2_glyf_exact_atlas"] = {
        "height": height,
        "glyf": glyf,
        "n_atlas": n_atlas,
        "allowed_n": len(allowed),
    }
    if n_atlas >= _MIN_ATLAS and glyf not in allowed:
        out.flags.append(V6Flag(
            code="TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN",
            detail=(
                f"F2 glyf={glyf} B вне точного корпуса height={height} "
                f"(allowed={sorted(allowed)}, n={n_atlas}) — Medium subset "
                f"с чужой страницы/донора (SEQ transplant F2) "
                f"(IGNORED: atlas novelty, not 0-FP)"
            ),
            tier="IGNORE",
            group="B5_font_rebuilder",
            rule_id="TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN",
        ))
    return out
