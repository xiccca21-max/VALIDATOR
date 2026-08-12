"""Alfa file-size envelopes by serializer family (Quartz iOS / Oracle BI).

Corpus чеки/альфа:
  Quartz/iOS  n=27  69706–71632
  Oracle BI   n=16  55326–59087

Strong outlier (beyond atlas ± pad) → HARD: PDF container weight is not from
the bank emitter family. Soft band → diagnostic only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .types import AlfaFlag

# (atlas_min, atlas_max, strong_lo, strong_hi)
_ENVELOPES: dict[str, tuple[int, int, int, int]] = {
    "quartz_ios": (69_706, 71_632, 67_500, 73_000),
    # Corpus max=59087 (n=30). SEQ Oracle shells sit at 59118–59796 — just
    # over atlas. strong_hi=atlas_max so any heavier byte is HARD oversize.
    "oracle_bi": (55_326, 59_087, 53_000, 59_087),
}


@dataclass
class CheckResult:
    flags: list[AlfaFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _producer_family(producer: str) -> str:
    p = (producer or "").lower()
    if "oracle" in p:
        return "oracle_bi"
    if "ios" in p or "quartz" in p:
        return "quartz_ios"
    return ""


def _producer_from_pdf(pdf_bytes: bytes) -> str:
    m = re.search(rb"/Producer\s*\(((?:[^()\\]|\\.)*)\)", pdf_bytes or b"")
    if not m:
        return ""
    return m.group(1).decode("latin1", "replace")


def check_file_size(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    generator_path: str = "",
) -> CheckResult:
    out = CheckResult()
    size = len(pdf_bytes or b"")
    out.stats["file_size"] = size
    family = generator_path if generator_path in _ENVELOPES else ""
    if not family:
        family = _producer_family(producer or _producer_from_pdf(pdf_bytes))
    out.stats["size_family"] = family
    if size <= 0 or family not in _ENVELOPES:
        return out

    a_min, a_max, strong_lo, strong_hi = _ENVELOPES[family]
    out.stats["size_atlas"] = {"min": a_min, "max": a_max}

    # Undersize is not future corpus growth — Oracle genuines ≥55326 (n=16);
    # stamp-less rebuilds land ~43KB (Документ (11).pdf). Oversize stays
    # diagnostic via ignored ALFA_FILE_SIZE_STRONG_OUTLIER.
    if size < strong_lo:
        out.flags.append(AlfaFlag(
            code="ALFA_FILE_SIZE_UNDERSIZE",
            detail=(
                f"вес PDF {size} B — сильно легче корпуса оригиналов Альфа "
                f"({family}: эталон {a_min}–{a_max}; HARD<{strong_lo})"
            ),
            tier="A",
            group="serializer_container",
            rule_id="ALFA_FILE_SIZE_UNDERSIZE",
        ))
    elif size > strong_hi:
        out.flags.append(AlfaFlag(
            code="ALFA_FILE_SIZE_STRONG_OUTLIER",
            detail=(
                f"вес PDF {size} B — сильно тяжелее корпуса оригиналов Альфа "
                f"({family}: эталон {a_min}–{a_max}; HARD-порог ≤{strong_hi})"
            ),
            tier="A",
            group="serializer_container",
            rule_id="ALFA_FILE_SIZE_STRONG_OUTLIER",
        ))
    elif size < a_min or size > a_max:
        out.flags.append(AlfaFlag(
            code="ALFA_FILE_SIZE_OUTLIER",
            detail=(
                f"вес PDF {size} B вне узкого эталона {family} ({a_min}–{a_max}) — "
                f"diagnostic"
            ),
            tier="DIAGNOSTIC",
            group="",
            rule_id="ALFA_FILE_SIZE_OUTLIER",
        ))
    return out
