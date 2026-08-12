"""T-Bank FontFile2 decoded-size envelopes by MediaBox height.

Genuine OpenPDF/Jasper receipts keep F1/F2 subset weights in a tight band for
each page height. SEQ rebuilds often inflate F1 (card/471) or F2 (sbp/519)
while keeping mosaic hashes clean.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

from .types import V6Flag

# MediaBox height → (f1_min, f1_max, f2_min, f2_max, n_atlas)
# From чеки/т банк OpenPDF corpus (n=128).
_FF2_BY_HEIGHT: dict[int, tuple[int, int, int, int, int]] = {
    411: (14_864, 15_840, 5_056, 5_512, 11),
    431: (15_072, 16_044, 5_056, 5_868, 40),
    451: (15_496, 16_596, 5_056, 5_420, 12),
    471: (15_252, 15_896, 5_044, 6_120, 8),
    473: (16_016, 16_016, 5_296, 5_296, 1),
    519: (16_244, 18_196, 5_000, 5_824, 48),
    539: (16_400, 17_428, 5_092, 5_420, 8),
}

_SLACK = 200
_MIN_ATLAS = 5


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


def _ff2_decoded_sizes(pdf_bytes: bytes) -> list[int]:
    sizes: list[int] = []
    for m in re.finditer(rb"/FontFile2\s+(\d+)\s+\d+\s+R", pdf_bytes or b""):
        onum = int(m.group(1))
        om = re.search(
            rf"(?m)^{onum}\s+0\s+obj\b.*?stream\r?\n(.*?)\n?endstream".encode(),
            pdf_bytes,
            re.S,
        )
        if not om:
            continue
        raw = om.group(1)
        try:
            dec = zlib.decompress(raw)
        except Exception:
            dec = raw
        sizes.append(len(dec))
    return sorted(sizes, reverse=True)


def check_fontfile2_size(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        return out
    height = _mediabox_height(pdf_bytes)
    sizes = _ff2_decoded_sizes(pdf_bytes)
    out.stats["mediabox_height"] = height
    out.stats["fontfile2_decoded_sizes"] = sizes
    if height is None or len(sizes) < 2:
        return out
    # Card FF2 envelopes FP competitor-accepted SEQ (finite n=8…40 ≠ all
    # genuines). Keep HARD only on SBP shell (h=519), same policy as glyf exact.
    if height != 519:
        out.stats["fontfile2_size_skipped"] = "non_sbp_height"
        return out
    env = _FF2_BY_HEIGHT.get(height)
    if not env:
        return out
    f1_min, f1_max, f2_min, f2_max, n_atlas = env
    out.stats["fontfile2_envelope"] = {
        "height": height,
        "f1": (f1_min, f1_max),
        "f2": (f2_min, f2_max),
        "n_atlas": n_atlas,
    }
    if n_atlas < _MIN_ATLAS:
        return out

    f1, f2 = sizes[0], sizes[1]
    # Exact atlas band (no slack). Genuines define min/max per height
    # (n=128 OpenPDF); SEQ CLEAN undershoot (180626 F2=4892 < 5056 @431)
    # and overshoot (180650 F1=16172 > 16044 @431; 180672 F1=15968 > 15896 @471).
    lo1, hi1 = f1_min, f1_max
    lo2, hi2 = f2_min, f2_max
    bad: list[str] = []
    if f1 < lo1 or f1 > hi1:
        side = "больше" if f1 > hi1 else "меньше"
        bad.append(
            f"F1 decoded {f1} B — сильно {side} эталона height={height} "
            f"(atlas {f1_min}–{f1_max}, n={n_atlas}; HARD {lo1}–{hi1})"
        )
    if f2 < lo2 or f2 > hi2:
        side = "больше" if f2 > hi2 else "меньше"
        bad.append(
            f"F2 decoded {f2} B — сильно {side} эталона height={height} "
            f"(atlas {f2_min}–{f2_max}, n={n_atlas}; HARD {lo2}–{hi2})"
        )
    if not bad:
        return out
    out.flags.append(V6Flag(
        code="TBANK_FONTFILE2_SIZE_STRONG_OUTLIER",
        detail="; ".join(bad),
        tier="A",
        group="B5_font_rebuilder",
        rule_id="TBANK_FONTFILE2_SIZE_STRONG_OUTLIER",
    ))
    return out
