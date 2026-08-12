"""
Универсальный движок валидатора банков по JSON-спекам (как alfa/tbank, но config-driven).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

from .corpus_signals import append_stats_only, emit_check
from .bank_channels import (
    CHANNEL_SBP,
    detect_channel,
    detect_subtype,
    receipt_subtype_label,
)
from .sbp_cipher import extract_sbp_opid, validate_nspk_sbp_cipher
from .structure import (
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .structure import find_streams, is_content_stream, content_skeleton_hash
from .forensics_profile import build_ff2_corpus, forensics_tier
from .ff2_pool import extract_fontfile2_streams
from .pdf_forensics import forensics_to_log_dict, run_pdf_forensics
from .ff2_pool import ff2_to_log_dict, run_ff2_pool_check
from .sber_sbp_layout import check_sber_sbp_layout
from .symbol_library import check_pdf_against_library, load_symbol_library_for
from .font_authenticity import (
    check_pdf_against_font_library,
    load_font_library_for,
)
from .anti_edit import run_checks as run_anti_edit_checks
from .full_bank import (
    _TIER_SKIP_STRUCTURE,
    _merge_forensics_filtered,
    _merge_incremental,
)
from .tbank import _SIGNALS
from .raif_content_cid0 import check_raif_content_cid0

_SPECS_DIR = Path(__file__).with_name("bank_specs")
_CACHE: dict[str, dict] = {}

_FOREIGN = (
    "pikepdf", "pypdf", "reportlab", "ilovepdf", "smallpdf", "pdfedit",
    "wkhtmltopdf", "libreoffice", "canva", "acrobat distiller",
)

_JASPER_CLONES = ("TinkoffSans", "jasperreports")

_YANDEX_OP_TIME_RE = re.compile(
    r"Дата\s+и\s+время\s+операции\s+МСК\s+(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{2}):(\d{2})",
    re.IGNORECASE,
)
_PDF_CREATION_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:Z|([+-])(\d{2})'?(?:(\d{2}))?'?)?"
)


def load_spec(bank_key: str) -> dict:
    if bank_key in _CACHE:
        return _CACHE[bank_key]
    path = _SPECS_DIR / f"{bank_key}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    _CACHE[bank_key] = data
    return data


def reload_specs() -> None:
    _CACHE.clear()


def _in_envelope(val: int | None, bounds: list | None) -> bool:
    if val is None or not bounds or len(bounds) != 2:
        return True
    return bounds[0] <= val <= bounds[1]


def _content_decoded(pdf_bytes: bytes) -> int:
    best = 0
    for _, dec in find_streams(pdf_bytes):
        if dec and is_content_stream(dec):
            best = max(best, len(dec))
    return best


def _pdf_creation_as_msk(value: str) -> datetime | None:
    m = _PDF_CREATION_RE.match(value or "")
    if not m:
        return None
    year, mo, day, hh, mm, ss = map(int, m.group(1, 2, 3, 4, 5, 6))
    sign = m.group(7)
    if sign:
        oh = int(m.group(8) or 0)
        om = int(m.group(9) or 0)
        offset = timedelta(hours=oh, minutes=om)
        if sign == "-":
            offset = -offset
        tz = timezone(offset)
    else:
        tz = timezone.utc
    created = datetime(year, mo, day, hh, mm, ss, tzinfo=tz)
    return created.astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None)


def _yandex_operation_time_msk(text: str) -> datetime | None:
    m = _YANDEX_OP_TIME_RE.search((text or "").replace("\xa0", " "))
    if not m:
        return None
    day, mo, year, hh, mm = map(int, m.groups())
    return datetime(year, mo, day, hh, mm)


def analyze(pdf_bytes: bytes, bank_key: str, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    spec = load_spec(bank_key)
    name = spec.get("name", bank_key)
    flags: list[str] = []
    details: dict = {"bank_key": bank_key}
    score = 0

    text, producer, creator, creation_date, mod_date = "", "", "", "", ""
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "".join(p.get_text() for p in doc)
            meta = doc.metadata or {}
            producer = (meta.get("producer") or "").strip()
            creator = (meta.get("creator") or "").strip()
            creation_date = (meta.get("creationDate") or "").strip()
            mod_date = (meta.get("modDate") or "").strip()
            doc.close()
        except Exception:
            pass

    channel = detect_channel(text, bank_key)
    subtype = detect_subtype(text, bank_key, name)
    details["receipt_subtype"] = subtype
    details["receipt_subtype_label"] = receipt_subtype_label(subtype, name, bank_key)
    details["channel"] = channel
    details["producer"] = producer
    details["creationDate"] = creation_date
    ch_spec = (spec.get("channels") or {}).get(channel, {})
    tier = forensics_tier(bank_key)
    details["forensics_tier"] = tier
    struct_skip = _TIER_SKIP_STRUCTURE.get(tier, frozenset())

    # ── PDF shell (как Т-Банк / full_bank) ────────────────────────────────────
    ignore_openaction = spec.get("ignore_openaction", False)
    _skip_active = frozenset((
        "OPENACTION_PRESENT", "DANGEROUS_ACTION_PRESENT",
    )) if ignore_openaction else frozenset()

    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        if code in struct_skip:
            continue
        flags.append(f"[{code}] {detail}")
        if code == "STREAM_DECOMPRESSION_FAILED":
            # Broken Flate streams can appear in genuine exports for some banks.
            # Keep this as a weak technical signal to avoid false positives.
            score += _SIGNALS["forensic_low"]
        else:
            score += _SIGNALS["forensic_high"] if any(
                x in code for x in ("INVALID", "MISMATCH", "FAILED")
            ) else _SIGNALS["forensic_medium"]

    s2 = validate_incremental_updates(pdf_bytes)
    flags, score = _merge_incremental(flags, score, s2)

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
        if code in _skip_active or code in struct_skip:
            continue
        flags.append(f"[{code}] {detail}")
        score += _SIGNALS["forensic_high"]

    xref_broken, xref_detail = xref_integrity(pdf_bytes)
    if xref_broken:
        flags.append(f"Целостность PDF нарушена: {xref_detail}")
        score += _SIGNALS["broken_xref"]

    combined = f"{producer} {creator}".lower()
    natives = tuple(p.lower() for p in spec.get("native_producers", ()))
    producer_ok = bool(natives and any(p in combined for p in natives))
    exact_producers = [
        str(x).strip() for x in (spec.get("native_producer_exact") or []) if str(x).strip()
    ]

    reserialized = len(re.findall(rb">>[ \t\r\n]+stream", pdf_bytes))
    if reserialized > 0 and natives and not producer_ok:
        flags.append(f"Потоки пересобраны сторонней библиотекой: {reserialized} шт.")
        score += _SIGNALS["stream_reserialized"]

    # ── Deep forensics (tiered, как full_bank) ────────────────────────────────
    forensic = run_pdf_forensics(pdf_bytes, bank=bank_key, tier=tier, channel=channel)
    flags, score = _merge_forensics_filtered(flags, score, details, forensic, tier)

    # ── Producer ──────────────────────────────────────────────────────────────
    if exact_producers:
        # Pin exact Generator strings when corpus is tiny (e.g. Sovkom Flying Saucer).
        # Substring natives alone accept clone kits on newer OpenPDF builds.
        prod_ok_exact = producer in exact_producers
        creat_ok_exact = (not creator) or creator in exact_producers
        if producer and not (prod_ok_exact and creat_ok_exact):
            expected = exact_producers[0]
            flags.append(
                f"[BANK_PRODUCER_VERSION_MISMATCH] Producer/Creator «{producer or '—'}» "
                f"/ «{creator or '—'}» ≠ эталон {name} «{expected}»"
            )
            score += _SIGNALS["forensic_high"]
    elif natives and not producer_ok:
        if not (spec.get("allow_empty_producer") and not combined.strip()):
            flags.append(f"[BANK_PRODUCER_MISMATCH] Producer «{producer}» не из эталона {name}")
            score += _SIGNALS["forensic_high"]

    for marker in _FOREIGN:
        if marker in combined:
            flags.append(f"[FOREIGN_PRODUCER] сторонний генератор «{marker}»")
            score += _SIGNALS["forensic_high"]
            break

    # ── Fonts ─────────────────────────────────────────────────────────────────
    if not spec.get("image_based"):
        req_fonts = spec.get("required_fonts", ())
        fonts_any = spec.get("required_fonts_any", False)

        def _font_hit(sub: str) -> bool:
            return sub.encode() in pdf_bytes or sub in (text or "")

        if req_fonts:
            if fonts_any:
                if not any(_font_hit(f) for f in req_fonts):
                    flags.append(
                        f"[BANK_FONT_MISSING] не найден ни один из шрифтов: "
                        f"{', '.join(req_fonts)}"
                    )
                    score += _SIGNALS["forensic_high"]
            else:
                for font_sub in req_fonts:
                    if not _font_hit(font_sub):
                        flags.append(f"[BANK_FONT_MISSING] не найден шрифт {font_sub}")
                        score += _SIGNALS["forensic_high"]

    if spec.get("reject_jasper_clone") and any(j in pdf_bytes for j in (
        b"TinkoffSans", b"jasperreports",
    )):
        flags.append("[BANK_JASPER_CLONE] обнаружен Jasper/TinkoffSans — чужой шаблон")
        score += _SIGNALS["forensic_high"]

    # ── Single FontFile2 profile (per channel) ───────────────────────────────
    # Sber/Alfa-style PDFs use one subset font, not T-Bank's F1/F2/F3 stack.
    # Hashes are stats only: a new genuine subset can produce a new hash.
    if spec.get("fontfile2_profile"):
        ff2_single = extract_fontfile2_streams(pdf_bytes)
        details["fontfile2_profile"] = {
            "count": len(ff2_single),
            "fonts": [
                {
                    "sha256_16": x.get("sha256_16"),
                    "size": x.get("size"),
                    "font_name": x.get("font_name"),
                }
                for x in ff2_single
            ],
        }
        expected_count = ch_spec.get("fontfile2_count")
        if expected_count and not _in_envelope(len(ff2_single), expected_count):
            lo, hi = expected_count
            flags.append(
                f"[BANK_FONTFILE2_COUNT_OUTLIER] FontFile2 слоёв {len(ff2_single)} "
                f"вместо эталона канала {channel} ({lo}–{hi})"
            )
            score += _SIGNALS["forensic_high"]
        expected_size = ch_spec.get("fontfile2_size")
        if expected_size and ff2_single:
            lo, hi = expected_size
            for font in ff2_single:
                size = int(font.get("size") or 0)
                if not _in_envelope(size, expected_size):
                    flags.append(
                        f"[BANK_FONTFILE2_SIZE_OUTLIER] FontFile2 {size} B вне "
                        f"эталона канала {channel} ({lo}–{hi})"
                    )
                    score += _SIGNALS["forensic_high"]
                    break
        expected_names = set(ch_spec.get("fontfile2_names") or [])
        if expected_names and ff2_single:
            actual = {
                (x.get("font_name") or "").split("+", 1)[-1]
                for x in ff2_single
                if x.get("font_name")
            }
            if actual and actual.isdisjoint(expected_names):
                flags.append(
                    f"[BANK_FONTFILE2_NAME_MISMATCH] шрифт {sorted(actual)} "
                    f"не из эталона канала {channel}: {sorted(expected_names)}"
                )
                score += _SIGNALS["forensic_high"]

    # ── Envelope ──────────────────────────────────────────────────────────────
    obj_count = len(re.findall(rb"\d+ 0 obj", pdf_bytes))
    details["object_count"] = obj_count
    if spec.get("object_count") and not _in_envelope(obj_count, spec["object_count"]):
        lo, hi = spec["object_count"]
        flags.append(
            f"[BANK_OBJECT_COUNT_OUTLIER] объектов {obj_count} вне эталона ({lo}–{hi})"
        )
        score += _SIGNALS["forensic_high"]

    dec = _content_decoded(pdf_bytes)
    details["content_decoded"] = dec
    global_dec = spec.get("content_decoded_global")
    bounds = ch_spec.get("content_decoded") or global_dec
    if spec.get("require_content_stream", True) and not dec:
        flags.append("[BANK_CONTENT_STREAM_MISSING] текстовый content stream не найден")
        score += _SIGNALS["forensic_high"]
    elif bounds and dec and not _in_envelope(dec, bounds):
        lo, hi = bounds
        flags.append(
            f"[BANK_CONTENT_STREAM_OUTLIER] content stream {dec} вне корпуса ({lo}–{hi})"
        )
        score += _SIGNALS["forensic_high"]

    file_size = len(pdf_bytes)
    details["file_size"] = file_size
    if ch_spec.get("file_size") and not _in_envelope(file_size, ch_spec["file_size"]):
        lo, hi = ch_spec["file_size"]
        flags.append(f"[BANK_FILE_SIZE_OUTLIER] размер {file_size} вне эталона ({lo}–{hi})")
        score += _SIGNALS["forensic_high"]

    sk = content_skeleton_hash(pdf_bytes)
    details["content_skeleton"] = sk
    known_sk = (spec.get("skeleton_hashes") or {}).get(channel) or spec.get("skeleton_hashes_global")
    if known_sk and sk and sk not in known_sk:
        known_list = list(known_sk)
        known_preview = ", ".join(known_list[:3])
        append_stats_only(
            details,
            f"[BANK_CONTENT_SKELETON_UNKNOWN] скелет content stream {sk} "
            f"не встречался в эталоне {name} (известно {len(known_list)} шабл.; "
            f"примеры: {known_preview})",
        )

    # ── FF2 subset pool (если есть в корпусе) ───────────────────────────────
    ff2_corpus = build_ff2_corpus(bank_key, channel)
    if ff2_corpus:
        ff2_res = run_ff2_pool_check(pdf_bytes, corpus=ff2_corpus)
        details["ff2_pool"] = ff2_to_log_dict(ff2_res)
        for ff in ff2_res.flags:
            score += emit_check(
                details, flags, f"[{ff.code}] {ff.detail}", _SIGNALS["ff2_subset_unknown"],
            )

    # ── SBP cipher ────────────────────────────────────────────────────────────
    if channel == CHANNEL_SBP and spec.get("sbp_cipher", True):
        opid = extract_sbp_opid(text)
        details["sbp_opid"] = opid
        # Some genuine Gazprombank SBP receipts use a legacy OPID layout
        # (e.g. core like IA000) that does not match the NSPK soft-cipher model.
        # Treat it as a bank-specific variant and skip NSPK structural checks.
        if bank_key == "gazprombank" and opid and opid[22:27] == "IA000":
            details["sbp_cipher"] = {
                "flags": [],
                "stats": {"opid": opid, "variant": "gazprom_legacy"},
            }
        else:
            prefer_first = spec.get("date_prefer_first_line", bank_key == "tbank")
            cipher = validate_nspk_sbp_cipher(
                opid or "", text, prefer_first_line_date=prefer_first,
            )
            details["sbp_cipher"] = {
                "flags": [{"code": f.code, "detail": f.detail} for f in cipher.flags],
                "stats": cipher.stats,
            }
            seen: set[str] = set()
            sber_sbp_invalid = False
            for cf in cipher.flags:
                if cf.code in seen:
                    continue
                seen.add(cf.code)
                flags.append(f"[{cf.code}] {cf.detail}")
                score += _SIGNALS["forensic_high"]
                if bank_key == "sber" and cf.code in {
                    "SBP_CIPHER_MISSING",
                    "SBP_CIPHER_STRUCTURE",
                    "SBP_CIPHER_TIMESTAMP",
                    "SBP_CIPHER_REFERENCE",
                }:
                    sber_sbp_invalid = True
            if sber_sbp_invalid:
                flags.append(
                    "[SBER_SBP_OPID_INVALID] для Сбербанка идентификатор операции СБП "
                    "не соответствует банковскому формату"
                )
                score += _SIGNALS["forensic_high"]

    # ── Raif pdfHTML: CID 0 in content show ops (generator splice) ───────────
    if bank_key == "raif":
        cid0 = check_raif_content_cid0(
            pdf_bytes,
            bank_key=bank_key,
            producer=producer,
            text=text,
            channel=channel,
        )
        details["raif_content_cid0"] = cid0.stats
        for cf in cid0.flags:
            flags.append(f"[{cf.code}] {cf.detail}")
            score += _SIGNALS["forensic_high"]

    # ── Yandex Jasper/OpenPDF anchor ─────────────────────────────────────────
    # Genuine Yandex Bank receipts generated by Jasper/OpenPDF carry a PDF
    # CreationDate that matches the operation time in the text (UTC -> MSK).
    # This is not a corpus-size/skeleton drift signal; it is an internal
    # metadata consistency invariant.
    if bank_key == "yandex" and channel == CHANNEL_SBP and creation_date:
        op_time = _yandex_operation_time_msk(text)
        created_msk = _pdf_creation_as_msk(creation_date)
        details["yandex_creation_time"] = {
            "operation_msk": op_time.isoformat(timespec="minutes") if op_time else None,
            "created_msk": created_msk.isoformat(timespec="seconds") if created_msk else None,
        }
        if op_time and created_msk:
            delta = abs((created_msk.replace(second=0, microsecond=0) - op_time).total_seconds())
            details["yandex_creation_time"]["delta_seconds"] = int(delta)
            if delta > 120:
                flags.append(
                    "[YANDEX_CREATION_TIME_MISMATCH] время создания PDF "
                    f"{created_msk:%d.%m.%Y %H:%M:%S} МСК не совпадает с "
                    f"временем операции {op_time:%d.%m.%Y %H:%M} МСК"
                )
                score += _SIGNALS["forensic_high"]

    # ── Sber SBP deep layout/operator drift (safe mode, non-hard) ────────────
    if bank_key == "sber" and channel == CHANNEL_SBP:
        lay = check_sber_sbp_layout(pdf_bytes)
        details["sber_sbp_layout"] = {
            "flags": [{"code": f.code, "detail": f.detail} for f in lay.flags],
            "stats": lay.stats,
        }
        for lf in lay.flags:
            flags.append(f"[{lf.code}] {lf.detail}")
            score += _SIGNALS["forensic_low"]

    # ── Symbol library drift (safe mode, per bank/channel) ───────────────────
    sym_lib = load_symbol_library_for(bank_key, channel)
    if sym_lib and int(sym_lib.get("source_count") or 0) >= 8:
        sym = check_pdf_against_library(pdf_bytes, sym_lib)
        details["symbol_library"] = {
            "bank_key": bank_key,
            "channel": channel,
            "source_count": int(sym_lib.get("source_count") or 0),
            "flags": [{"code": f.code, "detail": f.detail} for f in sym.flags],
            "stats": sym.stats,
        }
        for sf in sym.flags:
            flags.append(f"[{sf.code}] {sf.detail}")
            score += _SIGNALS["forensic_low"]

    # ── Authentic embedded-font library ──────────────────────────────────────
    # Safe layer: subset size is ignored; only stable TTF tables/glyph programs
    # are compared. Hard only when a well-sampled channel shows a foreign font.
    font_lib = load_font_library_for(bank_key, channel)
    if font_lib:
        font_auth = check_pdf_against_font_library(pdf_bytes, font_lib)
        details["font_authenticity"] = {
            "bank_key": bank_key,
            "channel": channel,
            "source_count": int(font_lib.get("source_count") or 0),
            "flags": [{"code": f.code, "detail": f.detail} for f in font_auth.flags],
            "stats": font_auth.stats,
        }
        for ff in font_auth.flags:
            delta = (
                _SIGNALS["forensic_high"]
                if ff.code == "FONT_AUTH_FOREIGN_FONT"
                else _SIGNALS["forensic_low"]
            )
            score += emit_check(details, flags, f"[{ff.code}] {ff.detail}", delta)

    # ── Anti-edit (safe hard signals) ─────────────────────────────────────────
    anti = run_anti_edit_checks(
        pdf_bytes,
        bank_key=bank_key,
        text=text,
        content_decoded=dec,
        creation_date=creation_date,
        mod_date=mod_date,
        file_hash_value=file_hash,
    )
    details["anti_edit"] = {
        "flags": [{"code": f.code, "detail": f.detail} for f in anti.flags],
        "stats": anti.stats,
    }
    for af in anti.flags:
        flags.append(f"[{af.code}] {af.detail}")
        score += _SIGNALS["forensic_high"]

    details["validator_engine"] = "bank_spec"
    details["profile_version"] = spec.get("version", "bank_spec")

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
