"""Sber file-size envelopes by profile.

Strong deviation from atlas weight for the same profile → HARD (container is
not bank-emitted mass). Soft band → diagnostic only. Requires n_atlas≥5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import SberFlag

# (soft_lo, soft_hi, atlas_min, atlas_max, n_atlas)
_PROFILE_ENVELOPES: dict[str, tuple[int, int, int, int, int]] = {
    "sbp_outgoing": (98_000, 106_500, 102_293, 103_469, 13),
    "sbp_request": (98_000, 106_500, 102_147, 102_147, 1),
    # Genuines cluster ~44243–44948; SEQ slips sat ~41570–42652 under 8%-of-min floor.
    "sber_internal_jasper": (43_500, 47_000, 44_243, 44_948, 5),
    "sber_internal_pdfium": (42_000, 47_000, 44_531, 44_531, 1),
    "legacy_phone": (33_000, 48_000, 36_236, 36_236, 1),
    "card_other_ios": (34_000, 45_000, 38_736, 38_736, 1),
}

_STRONG_OVER_FRAC = 0.08
_STRONG_UNDER_FRAC = 0.08
# Absolute HARD floors override the fractional under-bound when tighter.
# SEQ ~41–42.6 KB with fake FontFile2 recompress; genuines ≥44243.
_STRONG_LO_ABS: dict[str, int] = {
    # Corpus min 44243 (n=15). SEQ joke shells sit a few bytes under
    # (e.g. 44238) while staying above the old 43500 soft floor.
    "sber_internal_jasper": 44_243,
}

@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_file_size(pdf_bytes: bytes, *, profile_id: str = "") -> CheckResult:
    out = CheckResult()
    size = len(pdf_bytes or b"")
    out.stats["file_size"] = size
    env = _PROFILE_ENVELOPES.get(profile_id or "")
    if not env or size <= 0:
        return out
    soft_lo, soft_hi, atlas_min, atlas_max, n_atlas = env
    out.stats["file_size_envelope"] = {
        "profile_id": profile_id,
        "soft_lo": soft_lo,
        "soft_hi": soft_hi,
        "atlas_min": atlas_min,
        "atlas_max": atlas_max,
        "n_atlas": n_atlas,
    }

    strong_hi = int(atlas_max * (1.0 + _STRONG_OVER_FRAC))
    strong_lo = int(atlas_min * (1.0 - _STRONG_UNDER_FRAC))
    abs_lo = _STRONG_LO_ABS.get(profile_id or "")
    if abs_lo is not None:
        strong_lo = max(strong_lo, abs_lo)
    allow_hard = n_atlas >= 5

    if allow_hard and (size > strong_hi or size < strong_lo):
        side = "тяжелее" if size > strong_hi else "легче"
        ref = atlas_max if size > strong_hi else atlas_min
        pct = abs(size - ref) / max(ref, 1) * 100.0
        out.flags.append(SberFlag(
            code="SBER_FILE_SIZE_STRONG_OUTLIER",
            detail=(
                f"вес PDF {size} B — сильно {side} эталона профиля {profile_id} "
                f"(atlas {atlas_min}–{atlas_max}, n={n_atlas}; "
                f"порог HARD {strong_lo}–{strong_hi}; Δ≈{pct:.1f}%)"
            ),
            tier="HARD",
            group="file_size",
            rule_id="SBER_FILE_SIZE_STRONG_OUTLIER",
        ))
        return out

    if size < soft_lo or size > soft_hi:
        out.flags.append(SberFlag(
            code="SBER_FILE_SIZE_OUTLIER",
            detail=(
                f"вес PDF {size} B вне мягкого диапазона профиля {profile_id} "
                f"({soft_lo}–{soft_hi}) — diagnostic"
            ),
            tier="DIAGNOSTIC",
            group="",
            rule_id="SBER_FILE_SIZE_OUTLIER",
        ))
    return out
