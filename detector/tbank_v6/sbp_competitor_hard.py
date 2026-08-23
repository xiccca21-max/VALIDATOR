"""Hard competitor-matching SBP assembly fingerprint.

Rule intent:
- target linked tuple 1|6|0|G1|004|00117|770901
- plus FontFile2 glyf overrun warning on embedded TinkoffSans-Regular
- excluding known benign 405-byte variant
"""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont

from ..ff2_pool import extract_fontfile2_stream_blobs
from ..sbp_cipher import extract_sbp_opid
from ..tbank_sbp_content import extract_sbp_opid_geometric

_WARN_RE = re.compile(r"too much glyph data: (\d+) excess bytes")
_TARGET_TUPLE = "1|6|0|G1|004|00117|770901"
_BENIGN_WARN_VALUES = frozenset({405})


@dataclass
class CompetitorHardResult:
    flags: list[tuple[str, str]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _tuple_from_opid(opid: str) -> str:
    if not opid or len(opid) != 32:
        return ""
    return "|".join([
        opid[14],      # route_marker
        opid[15],      # control
        opid[16],      # separator
        opid[17:19],   # class
        opid[19:22],   # slot
        opid[22:27],   # bank5
        opid[26:32],   # suffix
    ])


def _sbp_tuple7(pdf_bytes: bytes, text: str, sbp_stats: dict) -> str:
    fields = (sbp_stats.get("sbp_link_fields") or {})
    from_stats = "|".join(
        str(fields.get(k, ""))
        for k in ("route_marker", "control", "separator", "class", "slot", "bank5", "suffix")
    )
    if from_stats.strip("|"):
        return from_stats
    opid = extract_sbp_opid_geometric(pdf_bytes, text) or extract_sbp_opid(text or "") or ""
    return _tuple_from_opid(opid)


def _collect_glyf_warn_values(pdf_bytes: bytes) -> list[int]:
    vals: list[int] = []
    for item in extract_fontfile2_stream_blobs(pdf_bytes):
        name = str(item.get("font_name") or "")
        if "TinkoffSans-" not in name:
            continue
        ttf = item.get("bytes")
        if not isinstance(ttf, (bytes, bytearray)):
            continue
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            tt = TTFont(io.BytesIO(ttf))
            if "glyf" not in tt:
                continue
            glyf = tt["glyf"]
            for gname in tt.getGlyphOrder():
                try:
                    _ = glyf[gname].isComposite()
                except Exception:
                    continue
        vals.extend(int(v) for v in _WARN_RE.findall(buf.getvalue()))
    return vals


def check_sbp_competitor_hard(
    pdf_bytes: bytes,
    text: str = "",
    sbp_stats: dict | None = None,
) -> CompetitorHardResult:
    out = CompetitorHardResult()
    tuple7 = _sbp_tuple7(pdf_bytes, text, sbp_stats or {})
    warn_values: list[int] = []
    if tuple7 == _TARGET_TUPLE:
        warn_values = _collect_glyf_warn_values(pdf_bytes)
    uniq_values = sorted(set(warn_values))
    has_warn = bool(warn_values)
    has_only_benign = bool(uniq_values) and set(uniq_values).issubset(_BENIGN_WARN_VALUES)
    matched = tuple7 == _TARGET_TUPLE and not has_only_benign
    out.stats = {
        "tuple7": tuple7,
        "target_tuple7": _TARGET_TUPLE,
        "warn_count": len(warn_values),
        "warn_values": uniq_values,
        "benign_warn_values": sorted(_BENIGN_WARN_VALUES),
        "matched": matched,
    }
    if matched:
        out.flags.append((
            "TBANK_SBP_TUPLE_GLYF_RESIDUE_SIGNATURE",
            (
                "SBP linked tuple 1|6|0|G1|004|00117|770901 совпал с "
                f"FontFile2 glyph residue warn={uniq_values or ['not_observed']} "
                "(исключена benign-ветка 405)"
            ),
        ))
    return out
