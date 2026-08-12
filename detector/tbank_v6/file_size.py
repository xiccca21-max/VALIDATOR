"""T-Bank file-size envelope.

Genuine corpus чеки/т банк ≈ 58214–61100. Strong outlier → HARD.
Soft band → diagnostic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import V6Flag

_ATLAS_MIN = 58_214
_ATLAS_MAX = 61_100
_STRONG_LO = 52_000
# Was 63500 — SEQ templates at ~63478 slipped under the wire (atlas max 61100).
_STRONG_HI = 62_000
_SOFT_LO = 55_000
_SOFT_HI = 62_500


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_file_size(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    size = len(pdf_bytes or b"")
    out.stats["file_size"] = size
    if size <= 0:
        return out

    if size < _STRONG_LO or size > _STRONG_HI:
        side = "тяжелее" if size > _STRONG_HI else "легче"
        out.flags.append(V6Flag(
            code="TBANK_FILE_SIZE_STRONG_OUTLIER",
            detail=(
                f"вес PDF {size} B — сильно {side} корпуса оригиналов Т-Банка "
                f"(эталон ~{_ATLAS_MIN}–{_ATLAS_MAX}; HARD-порог {_STRONG_LO}–{_STRONG_HI})"
            ),
            tier="A",
            group="B1_serializer_container",
            rule_id="TBANK_FILE_SIZE_STRONG_OUTLIER",
        ))
    elif size < _SOFT_LO or size > _SOFT_HI:
        out.flags.append(V6Flag(
            code="TBANK_FILE_SIZE_OUTLIER",
            detail=(
                f"вес PDF {size} B вне мягкого диапазона оригиналов Т-Банка "
                f"({_SOFT_LO}–{_SOFT_HI}) — diagnostic"
            ),
            tier="DIAGNOSTIC",
            group="",
            rule_id="TBANK_FILE_SIZE_OUTLIER",
        ))
    return out
