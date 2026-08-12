"""
Ozon Банк — v1.0 future-safe full replacement validator.

Legacy logic: ozon_legacy.py (disabled for verdict at 100% rollout).
Decision engine: detector/ozon_v1/ (MASTER SPEC v1.0).
"""

from __future__ import annotations

from .ozon_v1.engine import VALIDATOR_VERSION, analyze as analyze_v1
from .ozon_v1.rollout import apply_rollout

__all__ = ["analyze", "VALIDATOR_VERSION", "analyze_v1"]


def analyze(
    pdf_bytes: bytes,
    file_hash: str = "",
    *,
    source_filename: str | None = None,
) -> dict:
    v1 = analyze_v1(pdf_bytes, file_hash, source_filename=source_filename)
    return apply_rollout(v1, pdf_bytes, file_hash)
