"""Загрузка инвариантов корпуса Альфа-Банка."""

from __future__ import annotations

import json
from pathlib import Path

from .alfa_profiles import CHANNEL_CARD, CHANNEL_SBP, detect_alfa_channel

_PATH = Path(__file__).with_name("alfa_invariants.json")


def load() -> dict:
    if _PATH.is_file():
        return json.loads(_PATH.read_text(encoding="utf-8"))
    return {}


def channel_envelope(text: str) -> dict:
    inv = load()
    ch = detect_alfa_channel(text)
    ch_data = inv.get("channels", {}).get(ch, {})
    return {"channel": ch, **ch_data}


def in_envelope(val: int | None, bounds: list[int] | None) -> bool:
    if val is None or not bounds or len(bounds) != 2:
        return True
    return bounds[0] <= val <= bounds[1]


def global_content_envelope() -> list[int] | None:
    """Объединённый min/max content stream по всем каналам — для новых подтипов."""
    inv = load()
    lo, hi = None, None
    for ch_data in inv.get("channels", {}).values():
        bounds = ch_data.get("content_decoded")
        if bounds and len(bounds) == 2:
            lo = bounds[0] if lo is None else min(lo, bounds[0])
            hi = bounds[1] if hi is None else max(hi, bounds[1])
    return [lo, hi] if lo is not None else None


def envelope_for_channel(channel: str) -> dict:
    """Профиль канала или global fallback."""
    inv = load()
    ch_data = dict(inv.get("channels", {}).get(channel, {}))
    if not ch_data.get("content_decoded"):
        g = global_content_envelope()
        if g:
            ch_data["content_decoded"] = g
    return ch_data
