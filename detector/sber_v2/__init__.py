"""SberBank PDF validator v2.0 — production engine (no shadow)."""

from .engine import VALIDATOR_VERSION, analyze

__all__ = ["analyze", "VALIDATOR_VERSION"]
