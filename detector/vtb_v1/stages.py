"""VTB v1.0 eight-stage pipeline (spec §4–13)."""

from __future__ import annotations

import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..pdf_forensics import Weight, run_pdf_forensics
from ..structure import (
    content_stream_bytes,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from ..vtb_profiles import (
    FAMILY_NEW,
    FAMILY_SBP_OUT,
    classify_family,
    detect_generator_path,
    extract_sbp_opid,
    family_label,
    is_vtb_receipt,
    parse_operation_datetime,
)
from ..vtb_sbp_cipher import validate_vtb_sbp_cipher
from .rules import DELETED_CODES, DIAGNOSTIC_CODES, HARD_CODES
from .types import PipelineResult, VtbFlag
from .verdict import ingest_flag

_MAX_BYTES = 8_000_000
_DIAGNOSTIC_STRUCTURE = frozenset({
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
})
_BAD_CONTROLS = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
}
_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
)


def _flag(
    code: str,
    detail: str,
    *,
    tier: str | None = None,
    group: str = "",
    rule_id: str = "",
    expected: str = "",
    actual: str = "",
) -> VtbFlag:
    if tier is None:
        if code in HARD_CODES:
            tier = "HARD"
        elif code in DIAGNOSTIC_CODES:
            tier = "DIAGNOSTIC"
        else:
            tier = "DIAGNOSTIC"
    if not group:
        if "SBP" in code:
            group = "identifier"
        elif "FONT" in code or "CID" in code or "CMAP" in code:
            group = "font"
        elif code.startswith("STREAM"):
            group = "stream"
        else:
            group = "container"
    return VtbFlag(
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


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str]:
    if not fitz:
        return "", "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        m = doc.metadata or {}
        doc.close()
        return (
            m.get("producer") or "",
            m.get("creator") or "",
            m.get("creationDate") or "",
            m.get("modDate") or "",
        )
    except Exception:
        return "", "", "", ""


def _stage_intake(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes:
        result.analysis_complete = False
    elif len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False
        result.stats["budget_exceeded"] = "file_size"


def _stage_preflight(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("raw_parser")
    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        if code in DELETED_CODES:
            continue
        if code in _DIAGNOSTIC_STRUCTURE:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="VTB-CONT-009"))
        else:
            ingest_flag(result, _flag(code, detail, rule_id="VTB-CONT-001"))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0:
                tail = pdf_bytes[last_eof + 5:]
                if tail.strip(b"\r\n \t"):
                    ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="VTB-CONT-004"))
                else:
                    ingest_flag(result, _flag(
                        "VTB_EOF_EOL_ONLY",
                        "после %%EOF только EOL/LF — штатно для openhtmltopdf",
                        tier="DIAGNOSTIC",
                        rule_id="VTB-CONT-004",
                    ))
            continue
        if code in _DIAGNOSTIC_STRUCTURE:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="VTB-CONT-009"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, rule_id="VTB-CONT-003"))

    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", detail or "нарушена xref", rule_id="VTB-CONT-007"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="VTB-STRM-001"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="VTB-STRM-007"))


def _stage_active(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        if code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="VTB-ACT-001"))


def _stage_content_ast(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("content_ast")
    content = content_stream_bytes(pdf_bytes) or b""
    if not content:
        return

    bt = len(re.findall(rb"\bBT\b", content))
    et = len(re.findall(rb"\bET\b", content))
    q_ops = len(re.findall(rb"\bq\b", content))
    Q_ops = len(re.findall(rb"\bQ\b", content))
    result.stats["bt_et"] = {"bt": bt, "et": et, "q": q_ops, "Q": Q_ops}

    if bt != et:
        ingest_flag(result, _flag(
            "VTB_BT_ET_MISMATCH",
            f"несбалансированные BT/ET: {bt} vs {et}",
            tier="HARD",
            group="visibility",
            rule_id="VTB-VIS-001",
        ))
    elif q_ops != Q_ops:
        ingest_flag(result, _flag(
            "VTB_VIS_OPERATOR_DRIFT",
            f"q/Q drift {q_ops}/{Q_ops} — штатно для openhtmltopdf",
            tier="DIAGNOSTIC",
            rule_id="VTB-VIS-009",
        ))

    if b"/CIDToGIDMap" in pdf_bytes and b"/Identity" not in pdf_bytes[:60000]:
        ingest_flag(result, _flag(
            "VTB_CIDTOGID_OBSERVATION",
            "отдельный CIDToGID stream (не /Identity) — штатный VTB profile",
            tier="DIAGNOSTIC",
            rule_id="VTB-FONT-012",
        ))


def _stage_fonts(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("fonts_cmap_glyph")
    forensic = run_pdf_forensics(pdf_bytes, bank="vtb", tier="universal")
    result.stats["forensics"] = forensic.stats

    _FONT_HARD = {
        "USED_CID_MISSING_FROM_CMAP", "CMAP_INVALID",
        "USED_CID_MISSING_FROM_W", "FONTFILE2_MISSING",
        "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
        "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
    }
    _VTB_DIAGNOSTIC = {
        "W_EXTRA_CID", "W_ARRAY_PRETTY_PRINTED", "CMAP_W_MISMATCH",
        "TOUNICODE_PROFILE_SHIFT", "GLYPH_COUNT_OUTLIER",
        "MISSING_WIDTH_TABLE", "TTF_HMTX_PROFILE_SHIFT", "TTF_HEAD_ANOMALY",
        "CONTENT_STREAM_PROFILE_MISMATCH", "CMAP_BFRANGE_ANOMALY",
    }

    for f in forensic.flags:
        if f.code in DELETED_CODES:
            continue
        if f.code in _VTB_DIAGNOSTIC:
            ingest_flag(result, _flag(
                f.code,
                f.detail + " — VTB: extra ToUnicode/CIDToGID допустимы",
                tier="DIAGNOSTIC",
                group="font",
                rule_id="VTB-FONT-013",
            ))
            continue
        if f.code in _FONT_HARD and f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", group="font", rule_id="VTB-FONT-002"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", rule_id="VTB-FONT-013"))


def _text_controls(text: str) -> VtbFlag | None:
    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        return _flag(
            "TEXT_LAYER_INCONSISTENT",
            f"управляющие символы в критических полях ({', '.join(controls)})",
            tier="HARD",
            group="semantic",
            rule_id="VTB-SEM-001",
        )
    return None


def _stage_semantics(
    pdf_bytes: bytes,
    text: str,
    result: PipelineResult,
    *,
    producer: str,
    creator: str,
    creation_date: str,
    mod_date: str,
    file_hash: str,
) -> None:
    result.completed_checks.append("semantic_geometry")
    generator = detect_generator_path(producer, creator)
    result.generator_path = generator
    result.stats["producer"] = producer

    if not is_vtb_receipt(text, pdf_bytes):
        result.not_vtb_receipt = True
        return

    family = classify_family(text)
    result.family = family
    result.stats["family"] = family
    result.stats["family_label"] = family_label(family)

    if family == FAMILY_NEW:
        result.new_coherent_profile = True
        ingest_flag(result, _flag(
            "VTB_NEW_PROFILE",
            "новый согласованный VTB-профиль",
            tier="DIAGNOSTIC",
            rule_id="VTB-SEM-010",
        ))
    else:
        ingest_flag(result, _flag(
            "VTB_GENERATOR_PATH",
            f"легитимный путь: {generator}",
            tier="DIAGNOSTIC",
            rule_id="VTB-META-001",
        ))

    ingest_flag(result, _flag(
        "VTB_FAMILY",
        f"семейство {family}: {family_label(family)}",
        tier="DIAGNOSTIC",
        rule_id="VTB-SEM-011",
    ))

    tc = _text_controls(text)
    if tc:
        ingest_flag(result, tc)

    op_dt = parse_operation_datetime(text)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    if family == FAMILY_SBP_OUT:
        opid = extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        cipher = validate_vtb_sbp_cipher(opid or "", text)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            tier = "DIAGNOSTIC" if cf.code == "VTB_SBP_ID_DRIFT" else "HARD"
            if cf.code.startswith("VTB_SBP"):
                ingest_flag(result, _flag(
                    cf.code, cf.detail, tier=tier,
                    group="identifier", rule_id=cf.rule_id,
                ))

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes,
        bank_key="vtb",
        text=text,
        content_decoded=content_len,
        creation_date=creation_date,
        mod_date=mod_date,
        file_hash_value=file_hash,
    )
    result.stats["anti_edit"] = ae.stats
    for af in ae.flags:
        if af.code == "OPERATION_ID_REUSED":
            result.cross_document_identity_conflict = True
            ingest_flag(result, _flag(
                af.code, af.detail, tier="HARD",
                group="cross_document", rule_id="VTB-XDOC-001",
            ))
        elif af.code == "PDF_MODDATE_EDITED":
            ingest_flag(result, _flag(af.code, af.detail, tier="DIAGNOSTIC"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="VTB-VIS-005"))


def _stage_parity(pdf_bytes: bytes, text: str, result: PipelineResult) -> None:
    result.completed_checks.append("differential_parity")
    if not fitz:
        result.analysis_complete = False
        return
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        t2 = doc[0].get_text() if doc.page_count else ""
        doc.close()
    except Exception:
        result.analysis_complete = False
        return
    if not text or not t2:
        return

    a = result.stats.get("sbp_opid")
    b = extract_sbp_opid(t2)
    if a and b and a != b:
        ingest_flag(result, _flag(
            "VTB_PARSER_PARITY_MISMATCH",
            f"sbp_id: parser A «{a}» ≠ parser B «{b}»",
            tier="HARD",
            group="parity",
            rule_id="VTB-PARSE-001",
            expected=str(a),
            actual=str(b),
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
    result.generator_path = detect_generator_path(producer, creator)
    _stage_fonts(pdf_bytes, result)

    _stage_semantics(
        pdf_bytes, text, result,
        producer=producer, creator=creator,
        creation_date=creation_date, mod_date=mod_date,
        file_hash=file_hash,
    )
    _stage_parity(pdf_bytes, text, result)
    result.completed_checks.append("cross_document_intelligence")
    return result
