"""Ловля реплик: чужой F1 / hmtx + чужая вёрстка на рендере."""

from __future__ import annotations

import fitz

from .corpus_profiles import detect_receipt_channel
from .ff2_pool import _load_corpus, extract_ff2_fingerprints
from .pdf_forensics import run_pdf_forensics
from .render_fingerprint import count_foreign_rows
from .structure import content_skeleton_hash
from .tbank_invariants import channel_skeleton_pool

_RENDER_MIN = 8


def _ff2_pools() -> dict[str, set[str]]:
    corpus = _load_corpus()
    return {k: set(v) for k, v in corpus.get("layers", {}).items()}


def _pdf_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text()
    doc.close()
    return text


def run_font_render_forgery_check(pdf_bytes: bytes, text: str = "") -> tuple[bool, str]:
    """
    Hard when layout on render is foreign AND font stack looks cloned/rebuilt.

    - F1 subset never seen in corpus + >=8 foreign render rows (24/25 fakes, 0/128 orig)
    - OR hmtx profile shift (rebuilt F1 metrics)
    - OR all FontFile2 from corpus but unknown assembly skeleton + foreign render
      (generator reused entire font stack from a real receipt)
    """
    if not text:
        text = _pdf_text(pdf_bytes)
    pools = _ff2_pools()
    if not pools.get("F1"):
        return False, "корпус FF2 не загружен"

    fps = extract_ff2_fingerprints(pdf_bytes)
    if not fps:
        return False, "FontFile2 не извлечены"

    foreign, checked = count_foreign_rows(pdf_bytes)
    if checked == 0 or foreign < _RENDER_MIN:
        return False, f"рендер в норме ({foreign} чужих полос, порог {_RENDER_MIN})"

    f1_hash = fps["F1"]["sha256_16"]
    f1_unknown = f1_hash not in pools.get("F1", set())
    f2_unknown = fps["F2"]["sha256_16"] not in pools.get("F2", set())
    f3_known = fps["F3"]["sha256_16"] in pools.get("F3", set())
    all_known = all(
        fps[layer]["sha256_16"] in pools.get(layer, set()) for layer in ("F1", "F2", "F3")
    )

    hmtx_shift = any(
        f.code == "TTF_HMTX_PROFILE_SHIFT"
        for f in run_pdf_forensics(pdf_bytes, bank="tbank").flags
    )

    channel = detect_receipt_channel(text)
    sk = content_skeleton_hash(pdf_bytes)
    sk_unknown = sk not in channel_skeleton_pool().get(channel, frozenset())

    reasons: list[str] = [f"{foreign} чужих полос рендера из {checked}"]

    if f1_unknown:
        reasons.append(
            f"F1 Regular не из корпуса ({f1_hash}, {fps['F1']['size']} B)"
        )
        if f2_unknown and f3_known:
            reasons.append("F2 пересобран, F3 банковский (украденный рубль)")
        return True, "; ".join(reasons)

    if hmtx_shift:
        reasons.append("F1 hmtx не совпадает с банковским профилем OpenPDF")
        return True, "; ".join(reasons)

    if sk_unknown and all_known:
        reasons.append(
            f"шрифты из корпуса, но сборка PDF чужая (skeleton {sk[:12]}…)"
        )
        return True, "; ".join(reasons)

    return False, f"F1 в корпусе, рендер {foreign}/{checked} — недостаточно"
