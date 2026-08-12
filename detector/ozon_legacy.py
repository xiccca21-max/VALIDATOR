"""Ozon receipt checks — legacy generic/spec engine (disabled at 100% ozon_v1 rollout)."""

from __future__ import annotations

from .generic_bank import analyze as generic_analyze


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    return generic_analyze(pdf_bytes, "ozon", file_hash)
