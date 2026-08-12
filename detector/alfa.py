"""Альфа-Банк — v2.0 production validator (Oracle BI + Quartz iOS).

Decision engine: detector/alfa_v2/ (HARD + Tier-B ≥2 groups).
Legacy v1 remains available under detector/alfa_v1/ for reference only.
"""

from __future__ import annotations

from .alfa_v2.engine import VALIDATOR_VERSION, analyze

__all__ = ["analyze", "VALIDATOR_VERSION"]
