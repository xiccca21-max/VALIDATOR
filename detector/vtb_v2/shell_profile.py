"""VTB openhtml shell / font-dict structural invariants.

Corpus: чеки/втб оригинал (n=15 openhtml): SFNT always
  (gasp, glyf, head, hhea, hmtx, loca, maxp) — no cvt/fpgm/prep, no PADD.
SBP outgoing additionally: /W CID-array runs ≥ 18.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .types import VtbFlag
from ..structure import find_streams

# Genuines: /W CID-array runs ∈ [18, 23]. CLEAN-miss fake coalesced to 16.
_SBP_WIDTHS_RUNS_MIN = 18

# All openhtml VTB genuines (SBP/phone/card) share this SFNT directory.
_OPENHTML_SFNT_ORDER = (
    "gasp", "glyf", "head", "hhea", "hmtx", "loca", "maxp",
)

_W_ARRAY_RE = re.compile(rb"/W\s*(\[(?:[^\[\]]|\[[^\]]*\])*\])")


@dataclass
class ShellProfileResult:
    flags: list[VtbFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _flag(code: str, detail: str) -> VtbFlag:
    return VtbFlag(code=code, detail=detail, tier="HARD", rule_id=code)


def _widths_run_count(pdf_bytes: bytes) -> int | None:
    """Count CID-run entries of the form `cid [w1 w2 ...]` inside /W."""
    m = _W_ARRAY_RE.search(pdf_bytes or b"")
    if not m:
        return None
    return len(re.findall(rb"\d+\s*\[", m.group(1)))


def _sfnt_orders(pdf_bytes: bytes) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for _raw, dec in find_streams(pdf_bytes or b""):
        if not (dec and len(dec) >= 12 and dec[:4] in (b"\x00\x01\x00\x00", b"OTTO")):
            continue
        n = struct.unpack(">H", dec[4:6])[0]
        if n <= 0 or 12 + n * 16 > len(dec):
            continue
        out.append(tuple(
            dec[12 + i * 16 : 16 + i * 16].decode("latin1", "replace")
            for i in range(n)
        ))
    return out


def check_sbp_shell_profile(
    pdf_bytes: bytes,
    *,
    subtype: str,
    generator_path: str = "",
) -> ShellProfileResult:
    """Structural shell checks for VTB openhtml receipts."""
    out = ShellProfileResult()
    openhtml_subtypes = {
        "vtb_sbp_outgoing",
        "vtb_internal_phone",
        "vtb_card_transfer",
    }
    if subtype not in openhtml_subtypes:
        return out
    if generator_path and generator_path != "openhtmltopdf":
        out.stats["shell_skipped_generator"] = generator_path
        return out

    orders = _sfnt_orders(pdf_bytes)
    out.stats["sfnt_orders"] = [list(o) for o in orders]
    if orders:
        for order in orders:
            tags = set(order)
            has_padd = "PADD" in tags
            missing_gasp = "gasp" not in tags
            unexpected_hint = [t for t in ("cvt ", "fpgm", "prep") if t in tags]
            order_ok = order == _OPENHTML_SFNT_ORDER
            if has_padd or missing_gasp or unexpected_hint or not order_ok:
                out.flags.append(_flag(
                    "VTB_OPENHTML_SFNT_ORDER_MISMATCH",
                    (
                        f"FontFile2 SFNT order={list(order)} — "
                        f"{'PADD-rebuild; ' if has_padd else ''}"
                        f"{'нет gasp; ' if missing_gasp else ''}"
                        f"{'лишние hinting ' + str(unexpected_hint) + '; ' if unexpected_hint else ''}"
                        f"эталон openhtml ВТБ {list(_OPENHTML_SFNT_ORDER)} (n=15)"
                    ),
                ))
                break

    if subtype != "vtb_sbp_outgoing":
        return out
    if b"/CIDFontType2" not in (pdf_bytes or b""):
        out.stats["shell_skipped_w"] = "no_cidfonttype2"
        return out

    n_runs = _widths_run_count(pdf_bytes)
    out.stats["cid_widths_runs"] = n_runs
    out.stats["cid_widths_runs_min"] = _SBP_WIDTHS_RUNS_MIN
    if isinstance(n_runs, int) and n_runs > 0 and n_runs < _SBP_WIDTHS_RUNS_MIN:
        out.flags.append(_flag(
            "VTB_SBP_WIDTHS_RUNS_TOO_FEW",
            (
                f"CIDFont /W runs={n_runs} < {_SBP_WIDTHS_RUNS_MIN} "
                f"(openhtml SBP корпус ≥{_SBP_WIDTHS_RUNS_MIN}; n=13) — "
                f"слишком плотная/пересобранная упаковка Widths"
            ),
        ))
    return out
