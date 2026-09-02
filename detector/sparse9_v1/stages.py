"""Sparse9 shared MB-core pipeline (spec §4–14)."""

from __future__ import annotations

import re

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..pdf_forensics import Weight, run_pdf_forensics
from ..sparse9_profiles import (
    BANK_CONTRACTS,
    check_total_arithmetic,
    classify_method,
    detect_issuer,
    extract_sbp_opid,
    method_label,
    parse_operation_datetime,
)
from ..sparse9_known import (
    OTP_KNOWN_FAKE_FILE_SHA256,
    OTP_KNOWN_FAKE_SBP_IDS,
    OTP_KNOWN_FAKE_SBP_TAILS,
    YANDEX_KNOWN_FAKE_FILE_SHA256,
)
from ..sparse9_sbp_cipher import validate_sparse9_sbp_cipher
from ..sparse9_yandex_openpdf import check_yandex_openpdf_invariants
from ..sparse9_new_issuers import (
    check_mts_invariants,
    check_rsbank_invariants,
    check_tochka_invariants,
    check_yoomoney_invariants,
)
from ..raif_content_cid0 import RULE_ID as RAIF_CID0_RULE, check_raif_content_cid0
from ..bank_channels import detect_channel
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..structure import (
    content_stream_bytes,
    find_streams,
    is_content_stream,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .rules import DELETED_CODES, HARD_CODES
from .types import MbFlag, PipelineResult
from .verdict import ingest_flag

_MAX_BYTES = 8_000_000
_DIAGNOSTIC_STRUCTURE = frozenset({
    "MULTIPLE_EOF_PRESENT", "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT", "INCREMENTAL_UPDATE_PRESENT",
})
_BAD_CONTROLS = {
    "\u200b": "zws", "\u200c": "zwnj", "\u200d": "zwj",
    "\u202a": "bidi", "\u202b": "bidi", "\u202e": "bidi",
}
_FONT_HARD = {
    "USED_CID_MISSING_FROM_CMAP", "USED_CID_MISSING_FROM_W", "CMAP_INVALID",
    "FONTFILE2_MISSING", "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
    "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
}
_FONT_DIAG = {
    "W_EXTRA_CID", "TOUNICODE_PROFILE_SHIFT", "GLYPH_COUNT_OUTLIER",
    "CMAP_W_MISMATCH", "W_ARRAY_PRETTY_PRINTED", "MISSING_WIDTH_TABLE",
    "CONTENT_STREAM_PROFILE_MISMATCH", "TTF_HMTX_PROFILE_SHIFT",
}


def _page_text_stream_ops(pdf_bytes: bytes) -> tuple[int, int, int, int]:
    best: tuple[int, int, int, int] | None = None
    total_bt = total_et = total_q = total_Q = 0
    for _, dec in find_streams(pdf_bytes):
        if not dec:
            continue
        if not (is_content_stream(dec) or (b"BT" in dec and (b"Tj" in dec or b"TJ" in dec))):
            continue
        bt = len(re.findall(rb"\bBT\b", dec))
        et = len(re.findall(rb"\bET\b", dec))
        q_ops = len(re.findall(rb"\bq\b", dec))
        Q_ops = len(re.findall(rb"\bQ\b", dec))
        total_bt += bt
        total_et += et
        total_q += q_ops
        total_Q += Q_ops
        if bt == et and bt > 0:
            if best is None or bt > best[0]:
                best = (bt, et, q_ops, Q_ops)
    if best:
        return best
    return total_bt, total_et, total_q, total_Q


def _pdf_opens(pdf_bytes: bytes) -> bool:
    if not fitz:
        return True
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        ok = doc.page_count > 0
        doc.close()
        return ok
    except Exception:
        return False


def _flag(
    code: str, detail: str, *, tier: str | None = None,
    group: str = "", rule_id: str = "",
    expected: str = "", actual: str = "",
) -> MbFlag:
    if tier is None:
        tier = "HARD" if code in HARD_CODES else "DIAGNOSTIC"
    return MbFlag(
        code=code, detail=detail, tier=tier, rule_id=rule_id or code,
        group=group, expected=expected, actual=actual,
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = doc[0].get_text() if doc.page_count else ""
        doc.close()
        return text
    except Exception:
        return ""


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str, str]:
    if not fitz:
        return "", "", "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        m = doc.metadata or {}
        fmt = m.get("format") or ""
        doc.close()
        return (
            m.get("producer") or "",
            m.get("creator") or "",
            m.get("creationDate") or "",
            m.get("modDate") or "",
            fmt,
        )
    except Exception:
        return "", "", "", "", ""


def _detect_generator(producer: str, creator: str) -> str:
    blob = f"{producer} {creator}".lower()
    if "jasperreports library version 7" in blob:
        return "jasper7_openpdf"
    if "dbo-print-forms" in blob:
        return "dbo_print_forms"
    if "jasperreports library version 6.12" in blob:
        return "jasper612_itext"
    if "jasperreports library version 6.21" in blob:
        return "jasper621_openpdf"
    if "quartz pdfcontext" in blob:
        return "ios_quartz"
    if "mpdf" in blob:
        return "mpdf"
    if "fastreport" in blob:
        return "fastreport"
    if "pdfcreator" in blob or "pdfproducer" in blob:
        return "pdfcreator"
    if "pdfhtml" in blob:
        return "itext_pdfhtml"
    if "itext® core 9" in blob or "itext core 9" in blob:
        return "itext_core9"
    if "flying saucer" in blob:
        return "flying_saucer"
    if "rpdf.0.9" in blob:
        return "rpdf09"
    return "unknown_coherent"


def _stage_intake(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes or len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False


def _stage_preflight(pdf_bytes: bytes, result: PipelineResult, bank_key: str = "") -> None:
    result.completed_checks.append("raw_parser")
    if pdf_bytes.startswith(b"%PDF-2.0"):
        ingest_flag(result, _flag(
            "MB_PDF20_PROFILE", "PDF 2.0 — штатный профиль Sovkom",
            tier="DIAGNOSTIC", rule_id="MB-CONT-011",
        ))
    if b"/Type /XRef" in pdf_bytes and b"\bxref\b" not in pdf_bytes:
        ingest_flag(result, _flag(
            "MB_XREF_STREAM", "xref stream вместо таблицы — diagnostic",
            tier="DIAGNOSTIC", rule_id="MB-CONT-011",
        ))

    s1 = validate_pdf_structure(pdf_bytes)
    decomp_fail = int(s1.stats.get("stream_decompress_failures") or 0)
    for code, detail in zip(s1.codes, s1.details):
        if code in DELETED_CODES:
            continue
        if code == "OBJECT_GRAPH_INCONSISTENT" and (
            pdf_bytes.startswith(b"%PDF-2.0") or b"/Type /XRef" in pdf_bytes
        ):
            ingest_flag(result, _flag(
                code, detail + " — PDF2/xref-stream profile",
                tier="DIAGNOSTIC", rule_id="MB-CONT-011",
            ))
            continue
        if code == "STREAM_DECOMPRESSION_FAILED" and decomp_fail == 1 and _pdf_opens(pdf_bytes):
            ingest_flag(result, _flag(
                code, detail + " — единичный ложный zlib",
                tier="DIAGNOSTIC", rule_id="MB-STRM-006",
            ))
            continue
        if code == "STREAM_LENGTH_MISMATCH" and bank_key == "uralsib" and _pdf_opens(pdf_bytes):
            ingest_flag(result, _flag(
                code, detail + " — rPDF.0.9 length quirk",
                tier="DIAGNOSTIC", rule_id="MB-STRM-006",
            ))
            continue
        tier = "DIAGNOSTIC" if code in _DIAGNOSTIC_STRUCTURE else "HARD"
        ingest_flag(result, _flag(code, detail, tier=tier, rule_id="MB-CONT-001"))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0 and pdf_bytes[last_eof + 5:].strip(b"\r\n \t"):
                ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="MB-CONT-004"))
            else:
                ingest_flag(result, _flag(
                    "MB_EOF_EOL_ONLY", "EOF tail whitespace only",
                    tier="DIAGNOSTIC", rule_id="MB-CONT-004",
                ))
            continue
        if code not in DELETED_CODES:
            tier = "DIAGNOSTIC" if code in _DIAGNOSTIC_STRUCTURE else "HARD"
            ingest_flag(result, _flag(code, detail, tier=tier, rule_id="MB-CONT-003"))

    broken, detail = xref_integrity(pdf_bytes)
    if broken and not (pdf_bytes.startswith(b"%PDF-2.0") or b"/Type /XRef" in pdf_bytes):
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", detail or "xref", rule_id="MB-CONT-007"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code == "UNEXPECTED_STREAM_FILTER" and "DCTDecode" in detail:
            ingest_flag(result, _flag(
                code, detail + " — DCTDecode штатен для logo/stamp",
                tier="DIAGNOSTIC", rule_id="MB-STRM-006",
            ))
        elif code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="MB-STRM-001"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="MB-STRM-006"))


def _stage_active(pdf_bytes: bytes, bank_key: str, producer: str, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    pr = (producer or "").lower()
    benign_openaction = (
        bank_key == "psb" and "fastreport" in pr
    ) or (
        bank_key == "otp" and "mpdf" in pr
    )
    for code, detail in zip(s_act.codes, s_act.details):
        if code in DELETED_CODES:
            continue
        if benign_openaction and code in ("OPENACTION_PRESENT", "DANGEROUS_ACTION_PRESENT"):
            ingest_flag(result, _flag(
                code, detail + " — штатный OpenAction FastReport/mPDF",
                tier="DIAGNOSTIC", rule_id="MB-ACT-006",
            ))
            continue
        ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="MB-ACT-001"))


def _stage_content_ast(
    pdf_bytes: bytes,
    result: PipelineResult,
    *,
    bank_key: str = "",
    producer: str = "",
    text: str = "",
) -> None:
    result.completed_checks.append("content_ast")
    bt, et, q_ops, Q_ops = _page_text_stream_ops(pdf_bytes)
    result.stats["bt_et"] = {"bt": bt, "et": et}
    if bt != et:
        ingest_flag(result, _flag(
            "MB_BT_ET_MISMATCH", f"BT/ET {bt}/{et}",
            tier="HARD", rule_id="MB-VIS-001",
        ))
    elif q_ops != Q_ops:
        ingest_flag(result, _flag(
            "MB_VIS_OPERATOR_DRIFT", f"q/Q {q_ops}/{Q_ops}",
            tier="DIAGNOSTIC", rule_id="MB-PROF-001",
        ))

    if bank_key == "raif":
        cid0 = check_raif_content_cid0(
            pdf_bytes,
            bank_key=bank_key,
            producer=producer,
            text=text,
            channel=detect_channel(text, bank_key),
        )
        result.stats["raif_content_cid0"] = cid0.stats
        for cf in cid0.flags:
            ingest_flag(result, _flag(
                cf.code, cf.detail, tier="HARD", rule_id=cf.rule_id or RAIF_CID0_RULE,
            ))


def _stage_fonts(pdf_bytes: bytes, bank_key: str, result: PipelineResult) -> None:
    result.completed_checks.append("fonts_cmap_glyph")
    tier = "jasper" if bank_key in ("wbbank", "yandex", "mts", "yoomoney") else "generic"
    forensic = run_pdf_forensics(pdf_bytes, bank=bank_key, tier=tier)
    result.stats["forensics"] = forensic.stats
    for f in forensic.flags:
        if f.code in DELETED_CODES:
            continue
        if f.code in _FONT_DIAG:
            ingest_flag(result, _flag(
                f.code, f.detail + " — MB: extra mapping diagnostic",
                tier="DIAGNOSTIC", rule_id="MB-FONT-011",
            ))
            continue
        if f.code in _FONT_HARD and f.weight == Weight.HIGH:
            if bank_key in ("sovkom", "tochka", "mts") and f.code == "MISSING_FONT_OBJECT":
                ingest_flag(result, _flag(
                    f.code, f.detail + " — Resources в object-stream / PDF2",
                    tier="DIAGNOSTIC", rule_id="MB-FONT-012",
                ))
                continue
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", rule_id="MB-FONT-001"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", rule_id="MB-FONT-010"))


def _stage_semantics(
    pdf_bytes: bytes, text: str, result: PipelineResult, *,
    producer: str, creator: str, creation_date: str, mod_date: str,
    file_hash: str, expected_bank: str,
) -> None:
    result.completed_checks.append("semantic_geometry")
    issuer = detect_issuer(text, producer, creator, pdf_bytes)
    result.stats["issuer_detected"] = issuer

    if issuer != expected_bank:
        result.not_bank_receipt = True
        return

    contract = BANK_CONTRACTS.get(expected_bank)
    if contract:
        result.stats["bank_spec_id"] = contract.spec_id
        result.stats["bank_display"] = contract.display_name

    generator = _detect_generator(producer, creator)
    result.generator_path = generator
    result.stats["producer"] = producer
    ingest_flag(result, _flag(
        "MB_GENERATOR_PATH", generator,
        tier="DIAGNOSTIC", rule_id="MB-PROF-001",
    ))

    # Sovkom corpus pin: only Flying Saucer 10.0.6 + OpenPDF 3.0.0 observed.
    if expected_bank == "sovkom":
        exact = "Flying Saucer 10.0.6 with OpenPDF 3.0.0"
        if (producer or creator) and (producer != exact or (creator and creator != exact)):
            ingest_flag(result, _flag(
                "BANK_PRODUCER_VERSION_MISMATCH",
                f"Producer/Creator «{producer or '—'}» / «{creator or '—'}» ≠ эталон «{exact}»",
                tier="HARD",
                rule_id="K-SOVKOM-PRODUCER-001",
            ))

    method = classify_method(text, expected_bank)
    result.method = method_label(method)
    result.stats["method_code"] = method
    ingest_flag(result, _flag(
        "MB_FAMILY", method_label(method),
        tier="DIAGNOSTIC", rule_id="MB-SEM-007",
    ))

    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        ingest_flag(result, _flag(
            "TEXT_LAYER_INCONSISTENT", f"controls: {controls}",
            tier="HARD", rule_id="MB-FONT-009",
        ))

    nbsp_hits = find_trailing_nbsp_padding(text)
    if nbsp_hits:
        ingest_flag(result, _flag(
            NBSP_CODE, padding_detail(nbsp_hits),
            tier="HARD", rule_id="MB-SEM-NBSP-001", group="fields",
        ))

    bad, detail = check_total_arithmetic(text)
    if bad:
        ingest_flag(result, _flag(
            "MB_TOTAL_ARITHMETIC_MISMATCH", detail,
            tier="HARD", rule_id="MB-SEM-002",
        ))

    # PSB-Retail «Заявление на перевод» with blank INN — executed bank docs never
    # leave ИНН as underscores (scam FastReport kit: 20.pdf / 21.pdf / …).
    if expected_bank == "psb":
        low = (text or "").lower()
        if (
            "заявление" in low
            and "перевод" in low
            and (
                re.search(r"инн\s*_+", text or "", flags=re.IGNORECASE) is not None
                or "инн ____________" in low
            )
        ):
            ingest_flag(result, _flag(
                "PSB_STATEMENT_BLANK_INN",
                "в исполненном заявлении ПСБ поле ИНН заполнено подчёркиваниями "
                "(пустой шаблон) — на оригиналах ИНН всегда цифры",
                tier="HARD",
                rule_id="K-PSB-STATEMENT-INN-001",
            ))

    opid = extract_sbp_opid(text)

    # Exact known OTP clone-kit pins (file / full id / shared NSPK tail).
    if expected_bank == "otp":
        if file_hash and file_hash.lower() in OTP_KNOWN_FAKE_FILE_SHA256:
            ingest_flag(result, _flag(
                "OTP_KNOWN_FILE_SIGNATURE",
                f"file SHA-256 совпал с известной фейковой серией ({file_hash[:16]}…)",
                tier="KNOWN",
                rule_id="K-OTP-FILE-001",
            ))
        if opid and opid in OTP_KNOWN_FAKE_SBP_IDS:
            ingest_flag(result, _flag(
                "OTP_KNOWN_FAKE_SBP_ID",
                f"SBP ID «{opid}» — известный фейковый идентификатор",
                tier="KNOWN",
                rule_id="K-OTP-SBP-001",
            ))
        elif opid and opid[22:32] in OTP_KNOWN_FAKE_SBP_TAILS:
            ingest_flag(result, _flag(
                "OTP_KNOWN_FAKE_SBP_TAIL",
                f"SBP tail «{opid[22:32]}» — хвост известного clone-kit (bank5+suffix)",
                tier="KNOWN",
                rule_id="K-OTP-SBP-TAIL-001",
            ))

    if expected_bank == "yandex":
        if file_hash and file_hash.lower() in YANDEX_KNOWN_FAKE_FILE_SHA256:
            ingest_flag(result, _flag(
                "YANDEX_KNOWN_FILE_SIGNATURE",
                f"file SHA-256 совпал с известной фейковой серией ({file_hash[:16]}…)",
                tier="KNOWN",
                rule_id="K-YANDEX-FILE-001",
            ))
        yandex_inv = check_yandex_openpdf_invariants(pdf_bytes)
        result.stats["yandex_openpdf"] = yandex_inv.stats
        for yf in yandex_inv.flags:
            ingest_flag(result, _flag(
                yf.code, yf.detail, tier="HARD", rule_id=yf.rule_id or yf.code,
            ))
        from ..bank_spec_engine import _pdf_creation_as_msk, _yandex_operation_time_msk
        op_msk = _yandex_operation_time_msk(text)
        created_msk = _pdf_creation_as_msk(creation_date)
        if op_msk and created_msk:
            delta = abs(
                (created_msk.replace(second=0, microsecond=0) - op_msk).total_seconds()
            )
            result.stats["yandex_creation_delta_sec"] = int(delta)
            if delta > 120:
                ingest_flag(result, _flag(
                    "YANDEX_CREATION_TIME_MISMATCH",
                    f"время создания PDF {created_msk:%d.%m.%Y %H:%M:%S} МСК "
                    f"не совпадает с временем операции {op_msk:%d.%m.%Y %H:%M} МСК",
                    tier="HARD",
                    rule_id="K-YANDEX-CREATIONTIME-001",
                ))

    _issuer_checkers = {
        "mts": check_mts_invariants,
        "yoomoney": check_yoomoney_invariants,
        "rsbank": check_rsbank_invariants,
        "tochka": check_tochka_invariants,
    }
    checker = _issuer_checkers.get(expected_bank)
    if checker:
        inv = checker(
            pdf_bytes, producer=producer, creator=creator, text=text,
        )
        result.stats[f"{expected_bank}_invariants"] = inv.stats
        for nf in inv.flags:
            ingest_flag(result, _flag(
                nf.code, nf.detail, tier="HARD", rule_id=nf.rule_id or nf.code,
            ))

    # Sovkom card originals have no NSPK id; phone/SBP clones often paste a
    # T-Bank-style A62… id — validate with the shared NSPK checker whenever present.
    if expected_bank == "sovkom" and opid:
        from ..sbp_cipher import validate_nspk_sbp_cipher
        result.stats["sbp_opid"] = opid
        cipher = validate_nspk_sbp_cipher(opid, text)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            ingest_flag(result, _flag(
                cf.code, cf.detail, tier="HARD",
                group="sbp", rule_id=getattr(cf, "rule_id", None) or cf.code,
            ))
    elif contract and contract.sbp_id_required and (
        method == "SBP_OUT" or bool(opid)
    ):
        # OTP/Raif/… phone templates may say «перевод по номеру телефона» while
        # still embedding NSPK id — validate whenever the id is present.
        # Missing-id HARD only when method is explicitly SBP_OUT.
        result.stats["sbp_opid"] = opid
        cipher = validate_sparse9_sbp_cipher(opid or "", text, expected_bank)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            tier = "DIAGNOSTIC" if cf.code == "MB_SBP_ID_DRIFT" else "HARD"
            ingest_flag(result, _flag(
                cf.code, cf.detail, tier=tier,
                group="sbp", rule_id=cf.rule_id,
            ))

    op_dt = parse_operation_datetime(text, expected_bank)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes, bank_key=expected_bank, text=text,
        content_decoded=content_len, creation_date=creation_date,
        mod_date=mod_date, file_hash_value=file_hash,
    )
    for af in ae.flags:
        if af.code == "OPERATION_ID_REUSED":
            result.cross_document_identity_conflict = True
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="MB-XDOC-001"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="MB-VIS-006"))


def _stage_parity(pdf_bytes: bytes, text: str, result: PipelineResult) -> None:
    result.completed_checks.append("differential_parity")
    if not fitz:
        return
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        t2 = doc[0].get_text() if doc.page_count else ""
        doc.close()
    except Exception:
        return
    a, b = result.stats.get("sbp_opid"), extract_sbp_opid(t2)
    if a and b and a != b:
        ingest_flag(result, _flag(
            "MB_PARSER_PARITY_MISMATCH",
            f"sbp_id A «{a}» ≠ B «{b}»",
            tier="HARD", rule_id="MB-PAR-001",
            expected=a, actual=b,
        ))


def run_pipeline(pdf_bytes: bytes, file_hash: str, bank_key: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash, bank_key=bank_key)
    _stage_intake(pdf_bytes, result)
    if not result.analysis_complete:
        return result

    _stage_preflight(pdf_bytes, result, bank_key)
    _stage_streams(pdf_bytes, result)

    text = _pdf_text(pdf_bytes)
    producer, creator, creation_date, mod_date, pdf_fmt = _pdf_metadata(pdf_bytes)
    result.stats["pdf_format"] = pdf_fmt
    result.stats["producer"] = producer

    _stage_active(pdf_bytes, bank_key, producer, result)
    _stage_content_ast(
        pdf_bytes, result, bank_key=bank_key, producer=producer, text=text,
    )
    _stage_fonts(pdf_bytes, bank_key, result)
    _stage_semantics(
        pdf_bytes, text, result,
        producer=producer, creator=creator,
        creation_date=creation_date, mod_date=mod_date,
        file_hash=file_hash, expected_bank=bank_key,
    )
    _stage_parity(pdf_bytes, text, result)
    result.completed_checks.append("cross_document_intelligence")
    return result
