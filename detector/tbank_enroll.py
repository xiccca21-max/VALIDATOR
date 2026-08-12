"""Зачисление подтверждённого оригинала Т-Банка в корпусные пулы."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .corpus_profiles import detect_receipt_channel
from .ff2_pool import extract_ff2_fingerprints, _load_corpus
from .render_fingerprint import merge_rows_into_library, save_row_library
from .structure import content_skeleton_hash

log = logging.getLogger(__name__)

_INV = Path(__file__).with_name("tbank_invariants.json")
_FF2 = Path(__file__).with_name("ff2_corpus.json")


def enroll_tbank_original(pdf_bytes: bytes, text: str) -> dict:
    """Добавить skeleton, FF2-triplet и строки рендера из подтверждённого оригинала."""
    ch = detect_receipt_channel(text)
    sk = content_skeleton_hash(pdf_bytes)
    added: dict = {"channel": ch, "skeleton": sk[:16], "ff2_triplet": False, "render_rows": False}

    if _INV.is_file():
        inv = json.loads(_INV.read_text(encoding="utf-8"))
        pool = inv.setdefault("channel_skeleton_hashes", {})
        lst = pool.setdefault(ch, [])
        if sk and sk not in lst:
            lst.append(sk)
            lst.sort()
            _INV.write_text(json.dumps(inv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            added["skeleton_added"] = True
        else:
            added["skeleton_added"] = False

    fp = extract_ff2_fingerprints(pdf_bytes)
    if fp:
        trip = [fp[l]["sha256_16"] for l in ("F1", "F2", "F3")]
        corpus = _load_corpus()
        trips = corpus.get("triplets") or []
        if trip not in trips:
            trips.append(trip)
            trips.sort()
            corpus["triplets"] = trips
            _FF2.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            added["ff2_triplet"] = True

    lib = merge_rows_into_library(pdf_bytes)
    save_row_library(lib)
    added["render_rows"] = True

    log.info("enrolled tbank original ch=%s sk=%s", ch, sk[:12])
    return added
