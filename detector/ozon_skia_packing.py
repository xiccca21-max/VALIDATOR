"""Ozon Chromium/Skia FontFile2 packing invariants.

Corpus чеки/озон чекии (n=34, all Skia): always 2×FontFile2, never PADD,
SFNT directory always:
  OS/2,cmap,cvt ,fpgm,gasp,glyf,head,hhea,hmtx,loca,maxp,name,post,prep
pre-BT content lines always 161.

Note: raw `stream` token count and MarkInfo heuristics vary across Skia
exports in the same corpus — do not HARD those without a stable counter.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .ozon_profiles import is_skia_chromium_profile
from .structure import content_stream_bytes, find_streams

_SKIA_SFNT_ORDER = (
    "OS/2", "cmap", "cvt ", "fpgm", "gasp", "glyf", "head",
    "hhea", "hmtx", "loca", "maxp", "name", "post", "prep",
)
_SKIA_FF2_COUNT = 2
_SKIA_PRE_BT_LINES = 161


@dataclass
class PackingFlag:
    code: str
    detail: str
    rule_id: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class PackingResult:
    flags: list[PackingFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


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


def _pre_bt_line_count(pdf_bytes: bytes) -> int | None:
    raw = content_stream_bytes(pdf_bytes) or b""
    if not raw:
        return None
    lines = raw.decode("latin1", "replace").splitlines()
    for i, ln in enumerate(lines):
        if "BT" in ln.split():
            return i
    return len(lines)


def check_ozon_skia_packing(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> PackingResult:
    """HARD packing signals for Chromium/Skia Ozon receipts only."""
    out = PackingResult()
    if not is_skia_chromium_profile(producer, creator):
        out.stats["skipped"] = "not_skia"
        return out

    orders = _sfnt_orders(pdf_bytes)
    out.stats["n_fontfile2"] = len(orders)
    out.stats["sfnt_orders"] = [list(o) for o in orders]
    out.stats["has_padd"] = any("PADD" in o for o in orders)

    if len(orders) != _SKIA_FF2_COUNT:
        out.flags.append(PackingFlag(
            code="OZON_SKIA_FONTFILE2_COUNT_MISMATCH",
            detail=(
                f"FontFile2 count={len(orders)} ≠ {_SKIA_FF2_COUNT} "
                f"(Skia Ozon корпус n=34)"
            ),
            rule_id="OZ-PACK-001",
            expected=str(_SKIA_FF2_COUNT),
            actual=str(len(orders)),
        ))

    for order in orders:
        tags = set(order)
        has_padd = "PADD" in tags
        order_ok = order == _SKIA_SFNT_ORDER
        if has_padd or not order_ok:
            out.flags.append(PackingFlag(
                code="OZON_SKIA_SFNT_ORDER_MISMATCH",
                detail=(
                    f"FontFile2 SFNT order={list(order)} — "
                    f"{'PADD-rebuild; ' if has_padd else ''}"
                    f"эталон Skia Ozon {list(_SKIA_SFNT_ORDER)} (n=34)"
                ),
                rule_id="OZ-PACK-002",
                expected=str(list(_SKIA_SFNT_ORDER)),
                actual=str(list(order)),
            ))
            break

    pre_n = _pre_bt_line_count(pdf_bytes)
    out.stats["pre_bt_lines"] = pre_n
    if isinstance(pre_n, int) and pre_n != _SKIA_PRE_BT_LINES:
        out.flags.append(PackingFlag(
            code="OZON_SKIA_PRE_BT_LINE_COUNT_MISMATCH",
            detail=(
                f"pre-BT lines={pre_n} ≠ {_SKIA_PRE_BT_LINES} "
                f"(Skia Ozon корпус n=34, все family)"
            ),
            rule_id="OZ-PACK-003",
            expected=str(_SKIA_PRE_BT_LINES),
            actual=str(pre_n),
        ))

    return out
