"""GPB v1.0 eight-stage pipeline (spec §4–14)."""

from __future__ import annotations

import re

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..gpb_profiles import (
    FAMILY_NEW,
    FAMILY_SBP_PHONE,
    check_total_arithmetic,
    classify_family,
    detect_emitter,
    detect_generator_path,
    extract_sbp_opid,
    family_label,
    is_gazprombank_receipt,
    parse_operation_datetime,
)
from ..gpb_sbp_cipher import validate_gpb_sbp_cipher
from ..gpb_sfnt_shell import check_gpb_sfnt_shell
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..pdf_forensics import Weight, run_pdf_forensics
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
from .rules import DELETED_CODES, DIAGNOSTIC_CODES, HARD_CODES
from .types import GpbFlag, PipelineResult
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


def _page_text_stream_ops(pdf_bytes: bytes) -> tuple[int, int, int, int]:
    """BT/ET/q/Q from balanced text content streams (Jasper Form XObject-safe)."""
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


def _flag(code: str, detail: str, *, tier: str | None = None, group: str = "", rule_id: str = "") -> GpbFlag:
    if tier is None:
        tier = "HARD" if code in HARD_CODES else "DIAGNOSTIC"
    return GpbFlag(code=code, detail=detail, tier=tier, rule_id=rule_id or code, group=group)


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


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str]:
    if not fitz:
        return "", "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        m = doc.metadata or {}
        doc.close()
        return m.get("producer") or "", m.get("creator") or "", m.get("creationDate") or "", m.get("modDate") or ""
    except Exception:
        return "", "", "", ""


def _stage_intake(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes or len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False


def _stage_preflight(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("raw_parser")
    s1 = validate_pdf_structure(pdf_bytes)
    decomp_fail = int(s1.stats.get("stream_decompress_failures") or 0)
    for code, detail in zip(s1.codes, s1.details):
        if code in DELETED_CODES:
            continue
        if code == "STREAM_DECOMPRESSION_FAILED" and decomp_fail == 1 and _pdf_opens(pdf_bytes):
            ingest_flag(result, _flag(
                code, detail + " — единичный ложный zlib в Jasper/PDF-A",
                tier="DIAGNOSTIC", rule_id="GPB-STRM-007",
            ))
            continue
        tier = "DIAGNOSTIC" if code in _DIAGNOSTIC_STRUCTURE else "HARD"
        ingest_flag(result, _flag(code, detail, tier=tier, rule_id="GPB-CONT-001"))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0 and pdf_bytes[last_eof + 5:].strip(b"\r\n \t"):
                ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="GPB-CONT-004"))
            else:
                ingest_flag(result, _flag("GPB_EOF_EOL_ONLY", "EOF tail whitespace only", tier="DIAGNOSTIC", rule_id="GPB-CONT-004"))
            continue
        if code not in DELETED_CODES:
            tier = "DIAGNOSTIC" if code in _DIAGNOSTIC_STRUCTURE else "HARD"
            ingest_flag(result, _flag(code, detail, tier=tier, rule_id="GPB-CONT-003"))

    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", detail or "xref", rule_id="GPB-CONT-007"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code == "UNEXPECTED_STREAM_FILTER" and "DCTDecode" in detail:
            ingest_flag(result, _flag(
                code, detail + " — DCTDecode штатен для GPB logo/stamp",
                tier="DIAGNOSTIC", rule_id="GPB-STRM-007",
            ))
        elif code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="GPB-STRM-001"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="GPB-STRM-007"))


def _stage_active(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        if code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="GPB-ACT-001"))


def _stage_content_ast(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("content_ast")
    bt, et, q_ops, Q_ops = _page_text_stream_ops(pdf_bytes)
    result.stats["bt_et"] = {"bt": bt, "et": et}
    if bt != et:
        ingest_flag(result, _flag("GPB_BT_ET_MISMATCH", f"BT/ET {bt}/{et}", tier="HARD", rule_id="GPB-VIS-001"))
    elif q_ops != Q_ops:
        ingest_flag(result, _flag("GPB_VIS_OPERATOR_DRIFT", f"q/Q {q_ops}/{Q_ops}", tier="DIAGNOSTIC", rule_id="GPB-VIS-009"))


def _stage_fonts(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("fonts_cmap_glyph")
    shell = check_gpb_sfnt_shell(pdf_bytes)
    result.stats["sfnt_shell"] = shell.stats
    for sf in shell.flags:
        ingest_flag(result, _flag(
            sf.code, sf.detail, tier="HARD", rule_id=sf.rule_id or "GPB-PACK-001",
        ))
    forensic = run_pdf_forensics(pdf_bytes, bank="gazprombank", tier="jasper")
    result.stats["forensics"] = forensic.stats
    _FONT_HARD = {
        "USED_CID_MISSING_FROM_CMAP", "USED_CID_MISSING_FROM_W", "CMAP_INVALID",
        "FONTFILE2_MISSING", "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
        "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
    }
    _GPB_DIAG = {
        "W_EXTRA_CID", "TOUNICODE_PROFILE_SHIFT", "GLYPH_COUNT_OUTLIER",
        "CMAP_W_MISMATCH", "W_ARRAY_PRETTY_PRINTED", "MISSING_WIDTH_TABLE",
        "CONTENT_STREAM_PROFILE_MISMATCH", "TTF_HMTX_PROFILE_SHIFT",
    }
    for f in forensic.flags:
        if f.code in DELETED_CODES:
            continue
        if f.code in _GPB_DIAG:
            ingest_flag(result, _flag(f.code, f.detail + " — GPB: extra ToUnicode допустим", tier="DIAGNOSTIC", rule_id="GPB-FONT-013"))
            continue
        if f.code in _FONT_HARD and f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", rule_id="GPB-FONT-002"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", rule_id="GPB-FONT-013"))


def _stage_semantics(
    pdf_bytes: bytes, text: str, result: PipelineResult, *,
    producer: str, creator: str, creation_date: str, mod_date: str, file_hash: str,
) -> None:
    result.completed_checks.append("semantic_geometry")
    emitter = detect_emitter(text, pdf_bytes, file_hash)
    result.stats["emitter"] = emitter

    if emitter == "sber":
        result.reroute_bank = "sber"
        result.not_gpb_receipt = True
        return

    if not is_gazprombank_receipt(text, pdf_bytes, file_hash):
        result.not_gpb_receipt = True
        return

    generator = detect_generator_path(producer, creator)
    result.generator_path = generator
    result.stats["producer"] = producer

    family = classify_family(text)
    result.family = family
    result.stats["family_label"] = family_label(family)

    if family == FAMILY_NEW:
        result.new_coherent_profile = True
        ingest_flag(result, _flag("GPB_NEW_PROFILE", "новый GPB profile", tier="DIAGNOSTIC", rule_id="GPB-SEM-010"))
    else:
        ingest_flag(result, _flag("GPB_GENERATOR_PATH", generator, tier="DIAGNOSTIC", rule_id="GPB-META-003"))

    ingest_flag(result, _flag("GPB_FAMILY", family_label(family), tier="DIAGNOSTIC", rule_id="GPB-SEM-011"))

    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        ingest_flag(result, _flag("TEXT_LAYER_INCONSISTENT", f"controls: {controls}", tier="HARD", rule_id="GPB-SEM-001"))

    nbsp_hits = find_trailing_nbsp_padding(text)
    if nbsp_hits:
        ingest_flag(result, _flag(
            NBSP_CODE, padding_detail(nbsp_hits),
            tier="HARD", group="fields", rule_id="GPB-SEM-NBSP-001",
        ))

    bad, detail = check_total_arithmetic(text)
    if bad:
        ingest_flag(result, _flag("GPB_TOTAL_ARITHMETIC_MISMATCH", detail, tier="HARD", rule_id="GPB-SEM-003"))

    if family == FAMILY_SBP_PHONE:
        opid = extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        cipher = validate_gpb_sbp_cipher(opid or "", text)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            tier = "DIAGNOSTIC" if cf.code == "GPB_SBP_ID_DRIFT" else "HARD"
            ingest_flag(result, _flag(cf.code, cf.detail, tier=tier, group="identifier", rule_id=cf.rule_id))

    op_dt = parse_operation_datetime(text)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    # A-GPB-LATENT-RECEIPT-REVISION-001 + CreationDate skew
    from ..hardening_v2.g_graph_003 import (
        check_operation_after_pdf_creation,
        run_g_graph_003,
    )
    g3 = run_g_graph_003(pdf_bytes, text)
    result.stats["latent_revision"] = {
        k: g3.stats.get(k)
        for k in (
            "active_content_xrefs", "orphan_candidate_xrefs",
            "stable_identity_fields", "conflict_groups",
            "latent_xref", "latent_decoded_sha256",
            "active_version", "latent_version",
        )
        if k in g3.stats
    }
    for fl in g3.flags:
        detail = fl.split("] ", 1)[-1] if "] " in fl else fl
        if "GPB_OPERATION_AFTER_PDF_CREATION" in fl:
            continue  # handled below
        ingest_flag(result, _flag(
            "GPB_LATENT_RECEIPT_REVISION_CONFLICT",
            detail,
            tier="HARD",
            group="latent_revision",
            rule_id="A-GPB-LATENT-RECEIPT-REVISION-001",
        ))

    created = check_operation_after_pdf_creation(
        text, creation_date=creation_date, mod_date=mod_date,
    )
    result.stats["creation_skew"] = created.stats.get("creation_check")
    for fl in created.flags:
        ingest_flag(result, _flag(
            "GPB_OPERATION_AFTER_PDF_CREATION",
            fl.split("] ", 1)[-1] if "] " in fl else fl,
            tier="HARD",
            group="metadata",
            rule_id="GPB-META-CREATION-001",
        ))

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes, bank_key="gazprombank", text=text,
        content_decoded=content_len, creation_date=creation_date,
        mod_date=mod_date, file_hash_value=file_hash,
    )
    for af in ae.flags:
        if af.code == "OPERATION_ID_REUSED":
            result.cross_document_identity_conflict = True
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="GPB-XDOC-001"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="GPB-VIS-005"))


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
            "GPB_PARSER_PARITY_MISMATCH",
            f"sbp_id A «{a}» ≠ B «{b}»",
            tier="HARD", rule_id="GPB-PAR-001",
            expected=a, actual=b,
        ))


def run_pipeline(pdf_bytes: bytes, file_hash: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash)
    _stage_intake(pdf_bytes, result)
    if not result.analysis_complete:
        return result

    _stage_preflight(pdf_bytes, result)
    _stage_streams(pdf_bytes, result)
    _stage_active(pdf_bytes, result)
    _stage_content_ast(pdf_bytes, result)

    text = _pdf_text(pdf_bytes)
    producer, creator, creation_date, mod_date = _pdf_metadata(pdf_bytes)
    _stage_fonts(pdf_bytes, result)
    _stage_semantics(
        pdf_bytes, text, result,
        producer=producer, creator=creator,
        creation_date=creation_date, mod_date=mod_date, file_hash=file_hash,
    )
    _stage_parity(pdf_bytes, text, result)
    result.completed_checks.append("cross_document_intelligence")
    return result
