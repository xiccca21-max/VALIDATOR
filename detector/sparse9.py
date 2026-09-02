"""
Sparse 9 banks — v1.0 future-safe shared MB-core validator.

Banks: wbbank, otp, psb, bchpb, raif, rocket, sovkom, uralsib, yandex,
mts, yoomoney, rsbank, tochka.
"""

from __future__ import annotations

import hashlib

from .sparse9_v1.engine import VALIDATOR_VERSION, analyze as analyze_v1
from .sparse9_v1.rollout import apply_rollout, is_sparse9_bank

__all__ = ["analyze", "analyze_v1", "VALIDATOR_VERSION", "is_sparse9_bank"]


def analyze(pdf_bytes: bytes, bank_key: str, file_hash: str = "") -> dict:
    if not is_sparse9_bank(bank_key):
        from .sparse9_legacy import analyze as analyze_legacy
        return analyze_legacy(pdf_bytes, bank_key, file_hash)

    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    v1 = analyze_v1(pdf_bytes, bank_key, file_hash)
    return apply_rollout(v1, pdf_bytes, file_hash, bank_key)
