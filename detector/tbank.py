"""
Т-Банк — v6.0 full replacement validator.

Legacy logic lives in tbank_legacy.py and is NOT used.
Decision engine: detector/tbank_v6/ (MASTER SPEC v6.0).
"""

from __future__ import annotations

from .tbank_v6.engine import VALIDATOR_VERSION, analyze

# Совместимость: alfa/sber/full_bank импортируют веса при analyze_for()
from .tbank_legacy import _SIGNALS

__all__ = ["analyze", "VALIDATOR_VERSION", "_SIGNALS"]
