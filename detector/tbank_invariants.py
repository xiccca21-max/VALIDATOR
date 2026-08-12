"""Загрузка инвариантов корпуса Т-Банк (min–max по всем оригиналам)."""

from __future__ import annotations

import json
from pathlib import Path

from .corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    CONTENT_PROFILE_CARD,
    CONTENT_PROFILE_PHONE,
    CONTENT_PROFILE_SBP,
    detect_receipt_channel,
)

_PATH = Path(__file__).with_name("tbank_invariants.json")


def load() -> dict:
    if _PATH.is_file():
        return json.loads(_PATH.read_text(encoding="utf-8"))
    return {}


def channel_skeleton_pool() -> dict[str, frozenset[str]]:
    """Known content-stream skeleton hashes per transfer channel."""
    raw = load().get("channel_skeleton_hashes") or {}
    return {ch: frozenset(hashes) for ch, hashes in raw.items()}


def content_envelope(text: str) -> dict:
    """Профиль content stream: объединение всех оригиналов канала."""
    inv = load()
    ch = detect_receipt_channel(text)
    ch_data = inv.get("channels", {}).get(ch, {})

    def _rng(key: str, fallback: dict, fk: str) -> tuple[int, int]:
        if ch_data.get(key):
            lo, hi = ch_data[key]
            return lo, hi
        return fallback[f"{fk}_min"], fallback[f"{fk}_max"]

    fallbacks = {
        CHANNEL_SBP: CONTENT_PROFILE_SBP,
        CHANNEL_PHONE: CONTENT_PROFILE_PHONE,
        CHANNEL_CARD: CONTENT_PROFILE_CARD,
    }
    fb = fallbacks.get(ch, CONTENT_PROFILE_SBP)
    d_lo, d_hi = _rng("content_decoded", fb, "content_decoded")
    r_lo, r_hi = _rng("content_raw", fb, "content_raw")
    return {
        "channel": ch,
        "content_decoded_min": d_lo,
        "content_decoded_max": d_hi,
        "content_raw_min": r_lo,
        "content_raw_max": r_hi,
        "bt_count": ch_data.get("bt_count"),
        "template": "classic",
    }


def in_envelope(val: int | None, bounds: list[int] | None) -> bool:
    if val is None or not bounds or len(bounds) != 2:
        return True
    return bounds[0] <= val <= bounds[1]
