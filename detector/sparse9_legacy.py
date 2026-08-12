"""Sparse 9 banks — legacy bank_spec_engine (shadow baseline)."""

from __future__ import annotations

from .bank_spec_engine import analyze as spec_analyze


def analyze(pdf_bytes: bytes, bank_key: str, file_hash: str = "") -> dict:
    return spec_analyze(pdf_bytes, bank_key, file_hash)
