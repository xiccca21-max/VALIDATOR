"""GPB iText FontFile2 / logo packing invariants.

Corpus чеки/газпромбанк оригинал receipts (n=5; exclude non-receipt Документ-*):
- exactly 4×FontFile2
- SFNT directory always: cvt ,fpgm,glyf,head,hhea,hmtx,loca,maxp,prep (no PADD)
- exactly 1 DCTDecode Image XObject at 530×115
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .structure import find_streams

_GPB_SFNT_ORDER = (
    "cvt ", "fpgm", "glyf", "head", "hhea", "hmtx", "loca", "maxp", "prep",
)
_GPB_FF2_COUNT = 4
_GPB_LOGO_WH = (530, 115)


@dataclass
class ShellFlag:
    code: str
    detail: str
    rule_id: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class ShellResult:
    flags: list[ShellFlag] = field(default_factory=list)
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


def _dct_image_dims(pdf_bytes: bytes) -> list[tuple[int, int]]:
    """Width/Height for Image XObjects that use DCTDecode."""
    dims: list[tuple[int, int]] = []
    # Scan object dictionaries near /Subtype /Image
    for m in re.finditer(
        rb"<<[^>]*?/Subtype\s*/Image[^>]*?>>",
        pdf_bytes or b"",
        flags=re.DOTALL,
    ):
        blob = m.group(0)
        if b"/DCTDecode" not in blob and b"/Filter/DCTDecode" not in blob:
            # Filter may be written as array; accept DCT token nearby
            if b"DCTDecode" not in blob:
                continue
        wm = re.search(rb"/Width\s+(\d+)", blob)
        hm = re.search(rb"/Height\s+(\d+)", blob)
        if wm and hm:
            dims.append((int(wm.group(1)), int(hm.group(1))))
    return dims


def check_gpb_sfnt_shell(pdf_bytes: bytes) -> ShellResult:
    out = ShellResult()
    orders = _sfnt_orders(pdf_bytes)
    out.stats["n_fontfile2"] = len(orders)
    out.stats["sfnt_orders"] = [list(o) for o in orders]
    out.stats["has_padd"] = any("PADD" in o for o in orders)

    if not orders:
        out.stats["skipped"] = "no_fontfile2"
        return out

    if len(orders) != _GPB_FF2_COUNT:
        out.flags.append(ShellFlag(
            code="GPB_FONTFILE2_COUNT_MISMATCH",
            detail=(
                f"FontFile2 count={len(orders)} ≠ {_GPB_FF2_COUNT} "
                f"(квитанции GPB iText корпус n=5)"
            ),
            rule_id="GPB-PACK-002",
            expected=str(_GPB_FF2_COUNT),
            actual=str(len(orders)),
        ))

    for order in orders:
        tags = set(order)
        has_padd = "PADD" in tags
        order_ok = order == _GPB_SFNT_ORDER
        if has_padd or not order_ok:
            out.flags.append(ShellFlag(
                code="GPB_SFNT_ORDER_MISMATCH",
                detail=(
                    f"FontFile2 SFNT order={list(order)} — "
                    f"{'PADD-rebuild; ' if has_padd else ''}"
                    f"эталон iText GPB {list(_GPB_SFNT_ORDER)} (n=5)"
                ),
                rule_id="GPB-PACK-001",
                expected=str(list(_GPB_SFNT_ORDER)),
                actual=str(list(order)),
            ))
            break

    dims = _dct_image_dims(pdf_bytes)
    out.stats["dct_image_dims"] = dims
    if dims != [_GPB_LOGO_WH]:
        out.flags.append(ShellFlag(
            code="GPB_LOGO_DCT_DIMS_MISMATCH",
            detail=(
                f"DCT Image dims={dims} — эталон GPB logo "
                f"{list(_GPB_LOGO_WH)} ровно 1× (n=5)"
            ),
            rule_id="GPB-PACK-003",
            expected=str([list(_GPB_LOGO_WH)]),
            actual=str(dims),
        ))

    return out
