"""Sber v1.0 eight-stage pipeline (spec §4–13)."""

from __future__ import annotations

import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..pdf_forensics import Weight, run_pdf_forensics
from ..sber_profiles import (
    SUBMETHOD_P1,
    SUBMETHOD_P4,
    SUBMETHOD_P5,
    SUBMETHOD_P6,
    check_card_arithmetic,
    classify_submethod,
    detect_generator_path,
    extract_internal_document,
    extract_legacy_document,
    extract_sbp_opid,
    is_sber_receipt,
    parse_operation_datetime,
    submethod_label,
)
from ..sber_sbp_cipher import validate_legacy_document, validate_sber_sbp_cipher
from ..structure import (
    content_stream_bytes,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .rules import (
    DELETED_CODES,
    DIAGNOSTIC_CODES,
    HARD_CODES,
    _IOS_PRODUCER_MARKERS,
    _JASPER_MARKERS,
    _PDFIUM_MARKERS,
)
from .types import PipelineResult, SberFlag
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
_PDF_DATE_RE = re.compile(r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def _flag(
    code: str,
    detail: str,
    *,
    tier: str | None = None,
    group: str = "",
    rule_id: str = "",
    expected: str = "",
    actual: str = "",
    raw_evidence: str = "",
) -> SberFlag:
    if tier is None:
        if code in HARD_CODES:
            tier = "HARD"
        elif code in DIAGNOSTIC_CODES:
            tier = "DIAGNOSTIC"
        else:
            tier = "DIAGNOSTIC"
    if not group:
        if "SBP" in code or "LEGACY" in code or "DOCUMENT" in code:
            group = "identifier"
        elif "FONT" in code or "CID" in code or "CMAP" in code or "GLYPH" in code:
            group = "font"
        elif code.startswith("STREAM") or code == "UNEXPECTED_STREAM_FILTER":
            group = "stream"
        elif "JAVASCRIPT" in code or "ACTIVE" in code or "EMBEDDED" in code:
            group = "active"
        else:
            group = "container"
    return SberFlag(
        code=code, detail=detail, tier=tier, rule_id=rule_id or code,
        group=group, expected=expected, actual=actual, raw_evidence=raw_evidence,
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


def _parse_pdf_date(value: str) -> datetime | None:
    m = _PDF_DATE_RE.match(value or "")
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


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
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id=f"SBR-CONT-011"))
        else:
            ingest_flag(result, _flag(code, detail, rule_id=f"SBR-CONT-001"))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0:
                tail = pdf_bytes[last_eof + 5:]
                if tail.strip(b"\r\n \t"):
                    ingest_flag(result, _flag(
                        code, detail, tier="HARD", rule_id="SBR-CONT-004",
                    ))
                else:
                    ingest_flag(result, _flag(
                        "SBER_EOF_EOL_ONLY",
                        "после %%EOF только EOL — штатно для current profile",
                        tier="DIAGNOSTIC",
                        rule_id="SBR-CONT-004",
                    ))
            continue
        if code in _DIAGNOSTIC_STRUCTURE:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="SBR-CONT-012"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, rule_id="SBR-CONT-005"))

    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        ingest_flag(result, _flag(
            "XREF_OFFSET_INVALID", detail or "нарушена xref",
            rule_id="SBR-CONT-006",
        ))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="SBR-STRM-001"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="SBR-STRM-007"))


def _stage_active(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        if code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="SBR-GRAPH-001"))


def _content_stream_edit(content: bytes) -> tuple[bool, str]:
    pad_comments = [
        ln for ln in content.split(b"\n")
        if ln.strip().startswith(b"%") and len(ln.strip()) > 12
    ]
    if pad_comments:
        return True, f"padding-комментарии в content stream ({len(pad_comments)} строк)"
    et_pos = content.rfind(b"ET")
    if et_pos >= 0:
        after = content[et_pos + 2:]
        pad = len(after) - len(after.lstrip(b" \t\r\n\x0c"))
        if pad > 8:
            return True, f"хвостовой padding {pad} байт после ET"
    return False, ""


def _stage_content_ast(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("content_ast")
    content = content_stream_bytes(pdf_bytes)
    if not content:
        return
    bt = len(re.findall(rb"\bBT\b", content))
    et = len(re.findall(rb"\bET\b", content))
    q_ops = len(re.findall(rb"\bq\b", content))
    Q_ops = len(re.findall(rb"\bQ\b", content))
    result.stats["bt_et"] = {"bt": bt, "et": et, "q": q_ops, "Q": Q_ops}
    if bt != et:
        ingest_flag(result, _flag(
            "SBER_BT_ET_MISMATCH",
            f"несбалансированные BT/ET: {bt} vs {et}",
            tier="HARD",
            group="visibility",
            rule_id="SBR-VIS-001",
        ))
    elif q_ops != Q_ops:
        ingest_flag(result, _flag(
            "SBER_VIS_OPERATOR_DRIFT",
            f"q/Q count drift ({q_ops}/{Q_ops}) — штатно для Jasper/Quartz clipping",
            tier="DIAGNOSTIC",
            rule_id="SBR-VIS-009",
        ))
    cs_fake, cs_detail = _content_stream_edit(content)
    if cs_fake:
        ingest_flag(result, _flag(
            "SBER_CONTENT_STREAM_EDIT", cs_detail,
            tier="HARD", group="visibility", rule_id="SBR-VIS-003",
        ))
    if b" TJ" in content or b" Tc" in content:
        ingest_flag(result, _flag(
            "SBER_VIS_OPERATOR_DRIFT",
            "TJ/Tc/ICC operators — штатно для Quartz profile",
            tier="DIAGNOSTIC",
            rule_id="SBR-VIS-009",
        ))


def _sniff_generator(pdf_bytes: bytes, producer: str = "", creator: str = "") -> str:
    return detect_generator_path(producer, creator)


def _has_indirect_w(pdf_bytes: bytes) -> bool:
    return bool(re.search(rb"/W\s+\d+\s+0\s+R", pdf_bytes))


def _parse_indirect_w(pdf_bytes: bytes) -> dict[int, int]:
    from ..pdf_forensics import _parse_W_arrays

    inline = _parse_W_arrays(pdf_bytes)
    if inline:
        return inline
    m = re.search(rb"/W\s+(\d+)\s+0\s+R", pdf_bytes)
    if not m:
        return {}
    onum = int(m.group(1))
    obj_pat = rf"{onum} 0 obj\s*(\[)".encode()
    om = re.search(obj_pat, pdf_bytes)
    if not om:
        return {}
    start = om.end() - 1
    depth = 0
    end = start
    for i in range(start, min(len(pdf_bytes), start + 20000)):
        c = pdf_bytes[i:i + 1]
        if c == b"[":
            depth += 1
        elif c == b"]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    fake = b"/W " + pdf_bytes[start:end]
    return _parse_W_arrays(fake)


def _stage_fonts(pdf_bytes: bytes, result: PipelineResult, producer: str = "") -> None:
    result.completed_checks.append("fonts_cmap_glyph")
    gen = _sniff_generator(pdf_bytes, producer)
    result.stats["font_generator_sniff"] = gen

    forensic = run_pdf_forensics(pdf_bytes, bank="sber", tier="jasper")
    result.stats["forensics"] = forensic.stats

    _FONT_HARD_USED = {
        "USED_CID_MISSING_FROM_CMAP", "CMAP_INVALID",
        "USED_CID_MISSING_FROM_W", "FONTFILE2_MISSING",
        "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
        "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
    }
    _JASPER_DIAGNOSTIC = {
        "W_ARRAY_PRETTY_PRINTED", "W_ARRAY_SERIALIZATION_ANOMALY",
        "CMAP_W_MISMATCH", "W_EXTRA_CID", "MISSING_WIDTH_TABLE",
    }
    _IOS_SKIP_IF_INDIRECT_W = {
        "MISSING_WIDTH_TABLE", "USED_CID_MISSING_FROM_W",
    }

    has_indirect_w = _has_indirect_w(pdf_bytes)

    for f in forensic.flags:
        if f.code in DELETED_CODES:
            continue
        if gen in ("jasper_itext", "pdfium") and f.code in _JASPER_DIAGNOSTIC:
            ingest_flag(result, _flag(
                f.code, f.detail, tier="DIAGNOSTIC",
                group="font", rule_id="SBR-FONT-013",
            ))
            continue
        if gen == "ios_quartz" and has_indirect_w and f.code in _IOS_SKIP_IF_INDIRECT_W:
            ingest_flag(result, _flag(
                f.code,
                f.detail + " — iOS profile: /W в отдельном объекте (штатно)",
                tier="DIAGNOSTIC",
                group="font",
                rule_id="SBR-FONT-012",
            ))
            continue
        if f.code in _FONT_HARD_USED and f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", group="font", rule_id="SBR-FONT-002"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", group="font", rule_id="SBR-FONT-013"))


def _critical_field_controls(text: str) -> SberFlag | None:
    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        return _flag(
            "TEXT_LAYER_INCONSISTENT",
            f"невидимые управляющие символы в критических полях ({', '.join(controls)})",
            tier="HARD",
            group="semantic",
            rule_id="SBR-SEM-001",
        )
    return None


def _dynamic_now_check(text: str) -> SberFlag | None:
    if "сейчас" in (text or "").lower():
        return _flag(
            "SBER_DYNAMIC_NOW_IN_STATIC_RECEIPT",
            "в сохранённом PDF дата операции оставлена как «сейчас»",
            tier="HARD",
            group="semantic",
            rule_id="SBR-SEM-012",
        )
    return None


def _text_corrupt_check(text: str) -> list[SberFlag]:
    out: list[SberFlag] = []
    if "\x00" in text or "\ufffd" in text or "൚" in text:
        out.append(_flag(
            "SBER_TEXT_LAYER_CORRUPT",
            "в текстовом слое битые символы / неверный знак рубля",
            tier="HARD",
            group="semantic",
            rule_id="SBR-SEM-001",
        ))
    if re.search(r"\d+[.,]\d{2}\s*൚", text or ""):
        out.append(_flag(
            "SBER_AMOUNT_GLYPH_CORRUPT",
            "сумма напечатана с чужим glyph вместо ₽",
            tier="HARD",
            group="semantic",
            rule_id="SBR-FONT-008",
        ))
    return out


def _metadata_checks(
    text: str,
    creation: str,
    operation: datetime | None,
    generator: str,
) -> list[SberFlag]:
    out: list[SberFlag] = []
    creation_dt = _parse_pdf_date(creation)

    if generator == "pdfium" and not creation:
        out.append(_flag(
            "SBER_META_ABSENT",
            "PDFium export без CreationDate — штатно",
            tier="DIAGNOSTIC",
            rule_id="SBR-META-002",
        ))
        return out

    if creation_dt and operation and operation > creation_dt:
        delta_days = (operation - creation_dt).days
        if delta_days > 7:
            out.append(_flag(
                "SBER_META_CREATION_LATE",
                f"CreationDate на {delta_days} дней раньше операции — export/metadata ambiguity",
                tier="DIAGNOSTIC",
                rule_id="SBR-META-002",
            ))
        else:
            out.append(_flag(
                "SBER_OPERATION_AFTER_PDF_CREATION",
                "дата операции позже CreationDate — diagnostic при export ambiguity",
                tier="DIAGNOSTIC",
                rule_id="SBR-META-002",
            ))

    if (
        creation_dt and operation and operation < creation_dt
        and generator == "ios_quartz"
        and creation
    ):
        out.append(_flag(
            "SBER_META_OPERATION_BEFORE_CREATION",
            f"операция {operation} раньше CreationDate {creation_dt} при Quartz export",
            tier="HARD",
            group="metadata",
            rule_id="SBR-META-003",
            expected="operation ≤ CreationDate",
            actual=f"operation={operation}, creation={creation_dt}",
        ))

    return out


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
    generator = _sniff_generator(pdf_bytes, producer, creator)
    result.generator_path = generator
    result.stats["producer"] = producer
    result.stats["creator"] = creator
    result.stats["generator_path"] = generator

    if not is_sber_receipt(text, pdf_bytes):
        result.not_sber_receipt = True
        return

    submethod = classify_submethod(text, producer=producer, creator=creator)
    result.submethod = submethod
    result.stats["submethod"] = submethod
    result.stats["submethod_label"] = submethod_label(submethod)

    if generator == "unknown_coherent":
        result.new_coherent_profile = True
        ingest_flag(result, _flag(
            "SBER_NEW_PROFILE",
            f"новый согласованный generator path: «{producer[:60]}»",
            tier="DIAGNOSTIC",
            rule_id="SBR-META-001",
        ))
    else:
        ingest_flag(result, _flag(
            "SBER_GENERATOR_PATH",
            f"легитимный путь: {generator}",
            tier="DIAGNOSTIC",
            rule_id="SBR-META-001",
        ))

    ingest_flag(result, _flag(
        "SBER_SUBMETHOD",
        f"подметод {submethod}: {submethod_label(submethod)}",
        tier="DIAGNOSTIC",
        rule_id="SBR-SEM-011",
    ))

    if generator == "pdfium" and b"/Form" in pdf_bytes:
        ingest_flag(result, _flag(
            "SBER_PDFIUM_ORPHAN",
            "orphan empty Form — штатно для PDFium export (SBR-GRAPH-007)",
            tier="DIAGNOSTIC",
            rule_id="SBR-GRAPH-007",
        ))

    tc = _critical_field_controls(text)
    if tc:
        ingest_flag(result, tc)

    for f in _text_corrupt_check(text):
        ingest_flag(result, f)

    now_flag = _dynamic_now_check(text)
    if now_flag:
        ingest_flag(result, now_flag)

    op_dt = parse_operation_datetime(text)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    for mf in _metadata_checks(text, creation_date, op_dt, generator):
        ingest_flag(result, mf)

    if submethod == SUBMETHOD_P1:
        bad, detail = check_card_arithmetic(text)
        if bad:
            ingest_flag(result, _flag(
                "SBER_CARD_ARITHMETIC_MISMATCH",
                detail,
                tier="HARD",
                group="semantic",
                rule_id="SBR-SEM-003",
            ))

    if submethod in (SUBMETHOD_P5, SUBMETHOD_P6):
        opid = extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        cipher = validate_sber_sbp_cipher(opid or "", text)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            if cf.code in ("SBER_SBP_ID_MISSING", "SBER_SBP_ID_STRUCTURE", "SBER_SBP_ID_TIMESTAMP"):
                ingest_flag(result, _flag(
                    cf.code, cf.detail, tier="HARD",
                    group="identifier", rule_id=cf.rule_id,
                ))
            elif cf.code == "SBER_SBP_TAIL_UNKNOWN":
                ingest_flag(result, _flag(
                    cf.code, cf.detail, tier="DIAGNOSTIC",
                    group="identifier", rule_id=cf.rule_id,
                ))

    if submethod == SUBMETHOD_P4:
        legacy_doc = extract_legacy_document(text)
        result.stats["legacy_document"] = legacy_doc
        if legacy_doc:
            leg = validate_legacy_document(legacy_doc, text)
            result.stats["legacy_cipher"] = leg.stats
            for lf in leg.flags:
                if lf.code in ("SBER_LEGACY_DOC_STRUCTURE", "SBER_LEGACY_DOC_TIMESTAMP"):
                    ingest_flag(result, _flag(
                        lf.code, lf.detail, tier="HARD",
                        group="identifier", rule_id=lf.rule_id,
                    ))
        else:
            ingest_flag(result, _flag(
                "SBER_LEGACY_DOC_UNKNOWN",
                "legacy document ID не найден — diagnostic для нового шаблона",
                tier="DIAGNOSTIC",
                rule_id="SBR-SEM-011",
            ))

    internal_doc = extract_internal_document(text)
    if internal_doc:
        result.stats["internal_document"] = internal_doc

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes,
        bank_key="sber",
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
                group="cross_document", rule_id="SBR-XDOC-001",
            ))
        elif af.code == "PDF_MODDATE_EDITED":
            ingest_flag(result, _flag(af.code, af.detail, tier="DIAGNOSTIC", rule_id="SBR-META-002"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="SBR-VIS-007"))


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

    for extractor, a, b in (
        ("sbp_id", result.stats.get("sbp_opid"), extract_sbp_opid(t2)),
        ("legacy_doc", result.stats.get("legacy_document"), extract_legacy_document(t2)),
        ("internal_doc", result.stats.get("internal_document"), extract_internal_document(t2)),
    ):
        if a and b and a != b:
            ingest_flag(result, _flag(
                "SBER_PARSER_PARITY_MISMATCH",
                f"{extractor}: parser A «{a}» ≠ parser B «{b}»",
                tier="HARD",
                group="parity",
                rule_id="SBR-PARSE-001",
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
    result.generator_path = _sniff_generator(pdf_bytes, producer, creator)
    _stage_fonts(pdf_bytes, result, producer)

    _stage_semantics(
        pdf_bytes, text, result,
        producer=producer, creator=creator,
        creation_date=creation_date, mod_date=mod_date,
        file_hash=file_hash,
    )
    _stage_parity(pdf_bytes, text, result)
    result.completed_checks.append("cross_document_intelligence")
    return result
