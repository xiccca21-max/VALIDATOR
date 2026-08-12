"""
Full bank receipt analyzer — structure + forensics + envelope for all supported banks.

Tier 1 (Т-Банк СБП/телефон/карта) still uses detector/tbank.py.
All other banks use this module with tiered pdf_forensics.
"""

from __future__ import annotations

import hashlib
import re

from .corpus_profiles import CHANNEL_SBP, detect_receipt_channel
from .forensics_profile import (
    build_ff2_corpus,
    detect_channel_from_bytes,
    forensics_tier,
)
from .generic_bank import (
    FAKE_THRESHOLD,
    SUSPICIOUS_THRESHOLD,
    _BAD_PRODUCERS,
    _NATIVE_PRODUCERS,
    _WEIGHTS,
    _content_metrics,
    _in_range,
    _load_corpus,
    _producer_ok,
)
from .pdf_forensics import Weight, forensics_to_log_dict, run_pdf_forensics
from .ff2_pool import ff2_to_log_dict, run_ff2_pool_check
from .structure import (
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .tbank import _SIGNALS

_SBP_GENERIC = re.compile(r"[AB][0-9A-Z]{20,}", re.IGNORECASE)

# Сигналы, неприменимые к генераторам вне Jasper/OpenPDF (Oracle BI, openhtmltopdf, Skia…)
_TIER_SKIP_FORENSIC: dict[str, frozenset[str]] = {
    "universal": frozenset({
        "RASTER_OVERLAY_PRESENT", "TEXT_DRAWN_TWICE", "OVERLAY_TEXT_LAYER",
        "MASKING_RECTANGLE_PRESENT", "MASKING_GRAPHICS_NEAR_TEXT",
        "MISSING_WIDTH_TABLE", "FONTFILE2_MISSING", "FONTFILE_DESCRIPTOR_INCONSISTENT",
        "MULTIPLE_WEAK_ANOMALIES", "PROFILE_CLUSTER_OUTLIER", "CID_SEQUENCE_ANOMALY",
        "PAGE_RESOURCES_INCONSISTENT", "RESOURCE_REFERENCE_BROKEN",
        "XOBJECT_PROFILE_SHIFT",
    }),
    "jasper": frozenset({
        "RASTER_OVERLAY_PRESENT", "TEXT_DRAWN_TWICE", "OVERLAY_TEXT_LAYER",
        "MASKING_RECTANGLE_PRESENT", "MASKING_GRAPHICS_NEAR_TEXT",
        "MULTIPLE_WEAK_ANOMALIES", "PROFILE_CLUSTER_OUTLIER",
    }),
}

_TIER_SKIP_STRUCTURE: dict[str, frozenset[str]] = {
    "universal": frozenset({
        "STREAM_LENGTH_MISMATCH", "UNEXPECTED_STREAM_FILTER",
        "STREAM_COMPRESSION_RATIO_OUTLIER", "DECODED_STREAM_SIZE_OUTLIER",
        "OPENACTION_PRESENT", "DANGEROUS_ACTION_PRESENT",
    }),
    "jasper": frozenset({
        "STREAM_LENGTH_MISMATCH", "UNEXPECTED_STREAM_FILTER",
        "STREAM_COMPRESSION_RATIO_OUTLIER", "DECODED_STREAM_SIZE_OUTLIER",
        "OPENACTION_PRESENT", "DANGEROUS_ACTION_PRESENT",
    }),
}


def _merge_forensics_filtered(
    flags: list, score: int, details: dict, forensic, tier: str,
) -> tuple[list, int]:
    skip = _TIER_SKIP_FORENSIC.get(tier, frozenset())
    skip_prefixes = {"W_ARRAY_SERIALIZATION", "CMAP_BFRANGE", "TTF_HMTX", "TTF_HEAD"}
    seen: set[str] = set()
    for f in forensic.flags:
        if f.code in skip:
            continue
        if any(f.code.startswith(p) for p in skip_prefixes):
            continue
        if f.code in seen:
            continue
        seen.add(f.code)
        flags.append(f"[{f.code}] {f.detail}")
        if f.weight == Weight.HIGH:
            score += _SIGNALS["forensic_high"]
        elif f.weight == Weight.MEDIUM:
            score += _SIGNALS["forensic_medium"]
        else:
            score += _SIGNALS["forensic_low"]
    details["forensics"] = forensics_to_log_dict(forensic)
    details["forensic_template"] = forensic.template
    details["forensic_risk_bucket"] = forensic.checks.get("risk_bucket")
    return flags, score


def _check_sbp_text(text: str, channel: str) -> tuple[list[str], int]:
    flags: list[str] = []
    score = 0
    if channel != CHANNEL_SBP:
        return flags, score
    flat = re.sub(r"\s+", "", text)
    if _SBP_GENERIC.search(flat):
        return flags, score
    if any(m in text.lower() for m in (
        "идентификатор операции", "id операции", "номер операции в сбп",
        "идентификатор операции в сбп",
    )):
        return flags, score
    flags.append("Идентификатор операции СБП не найден")
    score += 70
    return flags, score


def _merge_incremental(flags: list, score: int, s2) -> tuple[list, int]:
    for code, detail in zip(s2.codes, s2.details):
        if code == "MULTIPLE_EOF_PRESENT":
            flags.append(detail)
            score += _SIGNALS["multiple_eof"]
        elif code in ("PREV_TRAILER_PRESENT", "INCREMENTAL_UPDATE_PRESENT"):
            flags.append(detail)
            score += _SIGNALS["prev_in_trailer"]
        else:
            flags.append(f"[{code}] {detail}")
            score += _SIGNALS["forensic_medium"]
    return flags, score


def analyze(pdf_bytes: bytes, bank_key: str, file_hash: str = "") -> dict:
    corpus = _load_corpus()
    bank = corpus.get("banks", {}).get(bank_key)
    if not bank:
        return {
            "verdict": "ЧИСТО",
            "emoji": "✅",
            "score": 0,
            "flags": ["Профиль банка не найден"],
            "details": {"bank_key": bank_key},
        }

    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    flags: list[str] = []
    score = 0
    details: dict = {
        "bank_key": bank_key,
        "bank_name": bank["name"],
        "validator": "full_bank_2.0",
        "forensics_tier": forensics_tier(bank_key),
    }

    text = ""
    producer = creator = ""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        meta = doc.metadata or {}
        producer = meta.get("producer", "") or ""
        creator = meta.get("creator", "") or ""
        doc.close()
    except Exception as e:
        details["text_error"] = str(e)

    channel = detect_receipt_channel(text) if text else detect_channel_from_bytes(pdf_bytes)
    ch_prof = bank.get("channels", {}).get(channel, {})
    details["channel"] = channel
    details["producer"] = producer
    details["creator"] = creator

    tier = forensics_tier(bank_key)
    struct_skip = _TIER_SKIP_STRUCTURE.get(tier, frozenset())

    # ── PDF shell (как Т-Банк) ───────────────────────────────────────────────
    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        if code in struct_skip:
            continue
        flags.append(f"[{code}] {detail}")
        score += (
            _SIGNALS["forensic_high"]
            if "INVALID" in code or "MISMATCH" in code or "FAILED" in code
            else _SIGNALS["forensic_medium"]
        )
    details["structure_codes"] = [c for c in s1.codes if c not in struct_skip]

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
        if code in struct_skip:
            continue
        flags.append(f"[{code}] {detail}")
        score += (
            _SIGNALS["forensic_high"]
            if "JAVASCRIPT" in code or "DANGEROUS" in code
            else _SIGNALS["forensic_low"]
        )
    details["active_content"] = [c for c in s_act.codes if c not in struct_skip]

    xref_broken, xref_detail = xref_integrity(pdf_bytes)
    if xref_broken:
        flags.append(f"Целостность PDF нарушена: {xref_detail}")
        score += _WEIGHTS["broken_xref"]

    reserialized = len(re.findall(rb">>[ \t\r\n]+stream", pdf_bytes))
    native = any(p in producer.lower() for p in _NATIVE_PRODUCERS)
    if reserialized > 0 and not native:
        flags.append(f"Потоки пересобраны сторонней библиотекой: {reserialized} шт.")
        score += _WEIGHTS["stream_reserialized"]

    for bp in _BAD_PRODUCERS:
        if bp in producer.lower():
            flags.append(f"Подозрительный Producer: «{producer}»")
            score += _WEIGHTS["suspicious_producer"]
            break

    # ── Deep forensics (tiered) ───────────────────────────────────────────────
    forensic = run_pdf_forensics(pdf_bytes, bank=bank_key, tier=tier, channel=channel)
    flags, score = _merge_forensics_filtered(flags, score, details, forensic, tier)

    # ── Bank/channel envelope ─────────────────────────────────────────────────
    metrics = _content_metrics(pdf_bytes)
    metrics["size"] = len(pdf_bytes)
    metrics["object_count"] = len(re.findall(rb"\d+ 0 obj", pdf_bytes))
    details["metrics"] = metrics

    allowed_prod = ch_prof.get("producers") or bank.get("known_producers") or []
    if not _producer_ok(producer, [p.lower() for p in allowed_prod]):
        flags.append(
            f"Producer «{producer or '—'}» не соответствует эталону "
            f"{bank['name']} ({channel})"
        )
        score += _WEIGHTS["producer_mismatch"]

    if ch_prof.get("content_decoded") and not metrics["content_decoded"]:
        flags.append(
            "Текстовый content stream не найден — структура PDF не совпадает "
            f"с эталонными чеками {bank['name']}"
        )
        score += _WEIGHTS["content_stream_drift"]
    elif not _in_range(metrics["content_decoded"], ch_prof.get("content_decoded")):
        lo, hi = ch_prof["content_decoded"]
        flags.append(
            f"Размер content stream {metrics['content_decoded']} вне профиля "
            f"оригиналов {bank['name']} ({lo}–{hi})"
        )
        score += _WEIGHTS["content_stream_drift"]

    if not _in_range(metrics["size"], ch_prof.get("file_size")):
        lo, hi = ch_prof["file_size"]
        flags.append(f"Размер файла {metrics['size']} вне профиля оригиналов ({lo}–{hi})")
        score += _WEIGHTS["file_size_drift"]

    if not _in_range(metrics["object_count"], ch_prof.get("object_count")):
        lo, hi = ch_prof["object_count"]
        flags.append(f"Число PDF-объектов {metrics['object_count']} вне профиля ({lo}–{hi})")
        score += _WEIGHTS["object_count_drift"]

    sbp_flags, sbp_score = _check_sbp_text(text, channel)
    flags.extend(sbp_flags)
    score += sbp_score

    # ── FF2 subset pool ───────────────────────────────────────────────────────
    ff2_corpus = build_ff2_corpus(bank_key, channel)
    if ff2_corpus:
        ff2_res = run_ff2_pool_check(pdf_bytes, corpus=ff2_corpus)
        details["ff2_pool"] = ff2_to_log_dict(ff2_res)
        for ff in ff2_res.flags:
            flags.append(f"[{ff.code}] {ff.detail}")
            score += _WEIGHTS["ff2_subset_unknown"]

    details["profile_version"] = corpus.get("version")

    from .verdict import finalize_verdict

    verdict, emoji, score, flags = finalize_verdict(score, flags)

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": score,
        "flags": flags,
        "details": details,
    }
