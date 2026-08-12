"""
Альфа-Банк — полный forensic analyzer (Oracle BI Publisher).

Аналог tbank.py, но без FontFile2 / glyf / Jasper font layers.
"""

from __future__ import annotations

import hashlib
import re

try:
    import fitz
except ImportError:
    fitz = None

from .alfa_profiles import ALFA_NATIVE_PRODUCERS, receipt_subtype_label
from .alfa_spec import run_alfa_spec_checks, spec_to_log_dict
from .forensics_profile import forensics_tier
from .full_bank import (
    _TIER_SKIP_STRUCTURE,
    _merge_forensics_filtered,
    _merge_incremental,
)
from .pdf_forensics import run_pdf_forensics
from .structure import (
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .tbank import _SIGNALS

VALIDATOR_VERSION = "1.0.0"
PROFILE_VERSION = "alfa_corpus_2026_06"


_ALFA_REASSEMBLY_CODES = {
    "CMAP_W_MISMATCH",
    "W_ARRAY_PRETTY_PRINTED",
    "W_ARRAY_SERIALIZATION_ANOMALY",
}


def _alfa_font_reassembly_flags(pdf_bytes: bytes) -> list[str]:
    """Return Alfa font-map diagnostics that are too noisy for a hard verdict."""
    raw_forensic = run_pdf_forensics(pdf_bytes)
    by_code = {f.code: f.detail for f in raw_forensic.flags}
    evidence = [
        f"{code}: {by_code[code]}"
        for code in _ALFA_REASSEMBLY_CODES
        if code in by_code
    ]
    return [f"[ALFA_FONT_MAP_DIAGNOSTIC] {'; '.join(evidence)}"] if evidence else []


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    flags: list[str] = []
    details: dict = {}
    score = 0
    tier = forensics_tier("alfa")
    details["forensics_tier"] = tier
    struct_skip = _TIER_SKIP_STRUCTURE.get(tier, frozenset())

    # ── PDF shell (как Т-Банк, с tier-skip для Oracle BI) ─────────────────────
    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        if code in struct_skip:
            continue
        flags.append(f"[{code}] {detail}")
        if "INVALID" in code or "MISMATCH" in code or "FAILED" in code:
            score += _SIGNALS["forensic_high"]
        else:
            score += _SIGNALS["forensic_medium"]
    details["structure_codes"] = s1.codes

    s2 = validate_incremental_updates(pdf_bytes)
    flags, score = _merge_incremental(flags, score, s2)
    details["incremental"] = s2.codes

    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in struct_skip:
            continue
        if "COMPRESSION" in code:
            flags.append(detail)
            score += _SIGNALS["wrong_zlib_level"]
        else:
            flags.append(f"[{code}] {detail}")
            score += _SIGNALS["forensic_low"]

    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        flags.append(f"[{code}] {detail}")
        if "JAVASCRIPT" in code or "DANGEROUS" in code or "ACROFORM" in code:
            score += _SIGNALS["forensic_high"]
        else:
            score += _SIGNALS["forensic_low"]
    details["active_content"] = s_act.codes

    xref_broken, xref_detail = xref_integrity(pdf_bytes)
    if xref_broken:
        flags.append(f"Целостность PDF нарушена: {xref_detail}")
        score += _SIGNALS["broken_xref"]

    # Oracle BI: >> stream — норма, не считаем reserialized
    reserialized = len(re.findall(rb">>[ \t\r\n]+stream", pdf_bytes))
    producer = ""
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            producer = (doc.metadata or {}).get("producer", "") or ""
            doc.close()
        except Exception:
            pass
    if reserialized > 0 and not any(p in producer.lower() for p in ALFA_NATIVE_PRODUCERS):
        flags.append(f"Потоки пересобраны сторонней библиотекой: {reserialized} шт.")
        score += _SIGNALS["stream_reserialized"]

    # ── Alfa-specific spec ────────────────────────────────────────────────────
    spec = run_alfa_spec_checks(pdf_bytes)
    details["alfa_spec"] = spec_to_log_dict(spec)
    channel = spec.stats.get("channel") or "phone"
    details["channel"] = channel
    details["receipt_subtype"] = spec.stats.get("receipt_subtype") or channel
    details["receipt_subtype_label"] = spec.stats.get("subtype_label")

    # ── Deep forensics (tier universal) ───────────────────────────────────────
    forensic = run_pdf_forensics(pdf_bytes, bank="alfa", tier=tier, channel=channel)
    flags, score = _merge_forensics_filtered(flags, score, details, forensic, tier)

    # Oracle BI can be cloned at the shell level while the embedded font maps are
    # rebuilt by fontTools/pypdf. Require two independent font-map anomalies so a
    # new genuine template is not rejected just for being outside the corpus.
    alfa_font_flags = _alfa_font_reassembly_flags(pdf_bytes)
    details["alfa_font_reassembly"] = alfa_font_flags
    for flag in alfa_font_flags:
        details.setdefault("stats_only", []).append(flag)

    seen: set[str] = set()
    for sf in spec.flags:
        if sf.code in seen:
            continue
        seen.add(sf.code)
        flags.append(f"[{sf.code}] {sf.detail}")
        score += _SIGNALS["forensic_high"]

    details["validator_version"] = VALIDATOR_VERSION
    details["profile_version"] = PROFILE_VERSION
    details["producer"] = producer

    from .verdict import finalize_verdict

    verdict, emoji, effective_score, forgery_flags = finalize_verdict(score, flags)
    details["user_message"] = (
        "Обнаружена подделка." if verdict == "ФЕЙК"
        else "Признаков подделки не найдено."
    )

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": effective_score,
        "flags": forgery_flags,
        "details": details,
    }
