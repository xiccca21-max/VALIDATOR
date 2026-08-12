"""Gazprombank receipt checks — legacy generic engine (disabled at 100% gpb_v1 rollout)."""

from __future__ import annotations

from .generic_bank import analyze as generic_analyze


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    return generic_analyze(pdf_bytes, "gazprombank", file_hash)
