"""
СберБанк — v2.0 production validator (tbank_v6-strength, no shadow).

Decision engine: detector/sber_v2/
"""

from __future__ import annotations

from .sber_v2.engine import VALIDATOR_VERSION, analyze

__all__ = ["analyze", "VALIDATOR_VERSION"]
