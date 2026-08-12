# -*- coding: utf-8 -*-
"""OpenPDF BaseFont subset-tag ↔ FontFile2 co-generation check.

Jasper stamps a unique 6-letter /BaseFont prefix per embedded subset.
Genuine corpus: tag → FF2 sha16 is bijective. SEQ freezes donor BaseFont
names while transplanting Regular/Medium FontFile2 payloads.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..tbank_reassembly_family_v3 import resolve_font_graph
from .basefont_subset_cogen_atlas import _F1_TAG_TO_FF2, _F2_TAG_TO_FF2
from .types import V6Flag

_BASEFONT_RE = re.compile(rb"/BaseFont\s*/([A-Z0-9]{6})\+([^\s/\[\]<>()]+)")


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _tags(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    reg = med = None
    for tag_b, face_b in _BASEFONT_RE.findall(pdf_bytes or b""):
        tag, face = tag_b.decode("ascii"), face_b.decode("latin1", "replace")
        if reg is None and "Regular" in face:
            reg = tag
        elif med is None and "Medium" in face:
            med = tag
    return reg, med


def check_basefont_subset_cogen(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        out.stats["skipped"] = "not_openpdf"
        return out

    reg_tag, med_tag = _tags(pdf_bytes)
    out.stats["basefont_regular_tag"] = reg_tag
    out.stats["basefont_medium_tag"] = med_tag
    if not reg_tag and not med_tag:
        out.stats["skipped"] = "no_subset_tags"
        return out

    try:
        graph = resolve_font_graph(pdf_bytes)
    except Exception as exc:  # noqa: BLE001 — forensic best-effort
        out.stats["skipped"] = f"font_graph:{type(exc).__name__}"
        return out

    mismatches: list[tuple[str, str, str, str]] = []

    f1 = graph.get("F1")
    if reg_tag and f1 and f1.fontfile2_decoded:
        got = _sha16(f1.fontfile2_decoded)
        expect = _F1_TAG_TO_FF2.get(reg_tag)
        out.stats["f1_tag_cogen"] = {
            "tag": reg_tag,
            "ff2_sha16": got,
            "expected": expect,
            "atlas_n": len(_F1_TAG_TO_FF2),
        }
        if expect is not None and got != expect:
            mismatches.append(("F1/Regular", reg_tag, expect, got))

    f2 = graph.get("F2")
    if med_tag and f2 and f2.fontfile2_decoded:
        got = _sha16(f2.fontfile2_decoded)
        expect = _F2_TAG_TO_FF2.get(med_tag)
        out.stats["f2_tag_cogen"] = {
            "tag": med_tag,
            "ff2_sha16": got,
            "expected": expect,
            "atlas_n": len(_F2_TAG_TO_FF2),
        }
        if expect is not None and got != expect:
            mismatches.append(("F2/Medium", med_tag, expect, got))

    out.stats["mismatch_n"] = len(mismatches)
    if not mismatches:
        return out

    parts = [
        f"{slot} tag={tag} ожидал FF2sha16={exp}, получено={got}"
        for slot, tag, exp, got in mismatches
    ]
    out.flags.append(
        V6Flag(
            code="TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH",
            detail=(
                "OpenPDF BaseFont subset-prefix заморожен с донора, а FontFile2 "
                "подменён (tag↔payload co-generation break): "
                + "; ".join(parts)
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_BASEFONT_SUBSET_TAG_PAYLOAD_MISMATCH",
        )
    )
    return out
