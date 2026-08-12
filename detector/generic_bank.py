"""
Generic bank receipt analyzer — structural checks calibrated per bank/channel.

Profiles: detector/bank_corpus.json (build via tools/build_bank_corpus.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

from .corpus_profiles import detect_receipt_channel
from .structure import (
    find_streams,
    is_content_stream,
    validate_active_content,
    validate_pdf_structure,
    xref_integrity,
)
from .ff2_pool import run_ff2_pool_check

_CORPUS_PATH = Path(__file__).with_name("bank_corpus.json")
_BAD_PRODUCERS = ("pikepdf", "pypdf", "ilovepdf", "smallpdf", "reportlab", "pdfedit", "wkhtmltopdf")
# Банковские генераторы легитимно пишут «>> stream» (Oracle BI, openhtmltopdf, …)
_NATIVE_PRODUCERS = (
    "oracle bi publisher", "openhtmltopdf", "fastreport", "itext",
    "skia/pdf", "rpdf", "openpdf", "quartz", "jasperreports",
)

FAKE_THRESHOLD = 60
SUSPICIOUS_THRESHOLD = 25

_WEIGHTS = {
    "broken_xref": 95,
    "stream_reserialized": 95,
    "suspicious_producer": 85,
    "producer_mismatch": 90,
    "content_stream_drift": 70,
    "file_size_drift": 65,
    "object_count_drift": 65,
    "ff2_subset_unknown": 95,
    "active_content": 95,
}


def _load_corpus() -> dict:
    if not _CORPUS_PATH.is_file():
        return {"banks": {}}
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _content_metrics(pdf_bytes: bytes) -> dict:
    best = {"content_decoded": 0, "content_raw": 0, "bt_count": 0}
    for raw, dec in find_streams(pdf_bytes):
        if dec and is_content_stream(dec) and len(dec) > best["content_decoded"]:
            best = {
                "content_decoded": len(dec),
                "content_raw": len(raw),
                "bt_count": dec.count(b"BT"),
            }
    return best


def _in_range(val: int | None, bounds: list[int] | None) -> bool:
    if val is None or not bounds or len(bounds) != 2:
        return True
    return bounds[0] <= val <= bounds[1]


def _producer_ok(producer: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    pl = (producer or "").lower()
    return any(a in pl for a in allowed)


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
    details: dict = {"bank_key": bank_key, "bank_name": bank["name"]}

    text = ""
    producer = creator = ""
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "".join(p.get_text() for p in doc)
            meta = doc.metadata or {}
            producer = meta.get("producer", "") or ""
            creator = meta.get("creator", "") or ""
            doc.close()
        except Exception as e:
            details["text_error"] = str(e)

    channel = detect_receipt_channel(text)
    ch_prof = bank.get("channels", {}).get(channel, {})
    details["channel"] = channel
    details["producer"] = producer
    details["creator"] = creator

    # ── Universal PDF shell ───────────────────────────────────────────────────
    ps = validate_pdf_structure(pdf_bytes)
    for code, det in zip(ps.codes, ps.details):
        if "INCREMENTAL" in code or "MULTIPLE_EOF" in code:
            flags.append(f"[{code}] {det}")

    xref_broken, xref_detail = xref_integrity(pdf_bytes)
    if xref_broken:
        flags.append(f"Целостность PDF нарушена: {xref_detail}")
        score += _WEIGHTS["broken_xref"]

    reserialized = len(re.findall(rb">>[ \t\r\n]+stream", pdf_bytes))
    native = any(p in producer.lower() for p in _NATIVE_PRODUCERS)
    if reserialized > 0 and not native:
        flags.append(f"Потоки пересобраны сторонней библиотекой: {reserialized} шт.")
        score += _WEIGHTS["stream_reserialized"]

    s_act = validate_active_content(pdf_bytes)
    for code, det in zip(s_act.codes, s_act.details):
        if "JAVASCRIPT" not in code:
            continue
        flags.append(f"[{code}] {det}")
        score += _WEIGHTS["active_content"]

    for bp in _BAD_PRODUCERS:
        if bp in producer.lower():
            flags.append(f"Подозрительный Producer: «{producer}»")
            score += _WEIGHTS["suspicious_producer"]
            break

    # ── Bank/channel profile (без T-Bank forensics — другой генератор) ────────
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

    # FF2 subset pool (only for banks with embedded font corpora)
    if ch_prof.get("ff2_triplets"):
        ff2_corpus = {
            "version": bank_key,
            "source_count": len(ch_prof.get("samples", [])),
            "layers": {"F1": set(), "F2": set(), "F3": set()},
            "triplets": ch_prof["ff2_triplets"],
        }
        for trip in ch_prof["ff2_triplets"]:
            for i, layer in enumerate(("F1", "F2", "F3")):
                ff2_corpus["layers"][layer].add(trip[i])
        ff2_corpus["layers"] = {k: list(v) for k, v in ff2_corpus["layers"].items()}

        ff2_res = run_ff2_pool_check(pdf_bytes, corpus=ff2_corpus)
        details["ff2_pool"] = {
            "flags": [{"code": f.code, "detail": f.detail} for f in ff2_res.flags],
            "stats": ff2_res.stats,
        }
        for ff in ff2_res.flags:
            flags.append(f"[{ff.code}] {ff.detail}")
            score += _WEIGHTS["ff2_subset_unknown"]

    details["profile_version"] = corpus.get("version")
    details["validator"] = "generic_bank_1.0"

    if score >= FAKE_THRESHOLD:
        verdict, emoji = "ФЕЙК", "🔴"
    else:
        verdict, emoji = "ЧИСТО", "✅"

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": score,
        "flags": flags,
        "details": details,
    }
