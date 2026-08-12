"""Per-bank forensic profiles from bank_corpus.json."""

from __future__ import annotations

import json
from pathlib import Path

from .corpus_profiles import detect_receipt_channel

_CORPUS_PATH = Path(__file__).with_name("bank_corpus.json")

# full — Т-Банк (все слои); jasper — OpenPDF/Jasper; universal — остальные
_FORENSICS_TIER: dict[str, str] = {
    "tbank": "full",
    "sber": "jasper",
    "yandex": "jasper",
    "gazprombank": "jasper",
}

_TBANK_FALLBACK = {
    "content_stream_min": 3000,
    "content_stream_max": 8000,
}


def _load_corpus() -> dict:
    if not _CORPUS_PATH.is_file():
        return {"banks": {}}
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def forensics_tier(bank_key: str) -> str:
    return _FORENSICS_TIER.get(bank_key, "universal")


def load_forensics_profile(bank_key: str, channel: str | None = None) -> dict:
    """Statistical envelope for pdf_forensics content-stream checks."""
    if bank_key == "tbank":
        return {
            "content_stream_min": 3000,
            "content_stream_max": 8000,
            "text_ops_count": 33,
            "bfrange_min": 30,
            "glyph_counts": {476, 479},
            "cid_density_max": 0.50,
            "unused_glyph_ratio_max": 0.48,
            "head_checksum_adj": 863796543,
            "hmtx_hashes": {"f45b998da9da", "6957d7a5e820"},
            "units_per_em": 1000,
        }

    corpus = _load_corpus()
    bank = corpus.get("banks", {}).get(bank_key, {})
    channels = bank.get("channels", {})
    prof: dict = {}

    ch_data = channels.get(channel or "", {})
    if not ch_data and channels:
        if channel and channel not in channels:
            ch_data = next(iter(channels.values()))
        elif len(channels) == 1:
            ch_data = next(iter(channels.values()))

    if ch_data.get("content_decoded"):
        lo, hi = ch_data["content_decoded"]
        prof["content_stream_min"] = lo
        prof["content_stream_max"] = hi
    elif channels:
        lows, highs = [], []
        for ch in channels.values():
            if ch.get("content_decoded"):
                lows.append(ch["content_decoded"][0])
                highs.append(ch["content_decoded"][1])
        if lows:
            prof["content_stream_min"] = min(lows)
            prof["content_stream_max"] = max(highs)

    return prof


def detect_channel_from_bytes(pdf_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return detect_receipt_channel(text)
    except Exception:
        return "phone"


def build_ff2_corpus(bank_key: str, channel: str) -> dict | None:
    corpus = _load_corpus()
    bank = corpus.get("banks", {}).get(bank_key)
    if not bank:
        return None
    ch = bank.get("channels", {}).get(channel, {})
    triplets = ch.get("ff2_triplets") or bank.get("ff2_triplets")
    layers = ch.get("ff2_layers") or bank.get("ff2_layers")
    if not triplets and not layers:
        return None
    ff2: dict = {
        "version": bank_key,
        "source_count": ch.get("sample_count") or len(ch.get("samples", [])) or bank.get("sample_count", 0),
        "bank_name": bank.get("name", bank_key),
        "triplets": triplets or [],
        "layers": {k: list(v) for k, v in (layers or {}).items()},
    }
    if not ff2["layers"] and triplets:
        ff2["layers"] = {"F1": set(), "F2": set(), "F3": set()}
        for trip in triplets:
            for i, layer in enumerate(("F1", "F2", "F3")):
                ff2["layers"][layer].add(trip[i])
        ff2["layers"] = {k: list(v) for k, v in ff2["layers"].items()}
    if not ff2["layers"].get("F1"):
        return None
    return ff2
