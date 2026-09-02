"""Ozon v1.0 pipeline (spec §4–14)."""

from __future__ import annotations

import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..ozon_profiles import (
    FAMILY_CARD_OUT,
    FAMILY_SBP_IN,
    FAMILY_SBP_OUT,
    check_total_arithmetic,
    classify_family,
    detect_generator_path,
    extract_po_uuid,
    extract_sbp_opid,
    family_label,
    is_ozon_receipt,
    parse_operation_datetime,
)
from ..ozon_sbp_content import validate_ozon_sbp_receipt
from ..ozon_sbp_tail import validate_ozon_sbp_tail_provenance
from ..ozon_serializer_mix import check_ozon_serializer_mix
from ..ozon_skia_packing import check_ozon_skia_packing
from ..pdf_forensics import Weight, run_pdf_forensics
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..structure import (
    content_stream_bytes,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .rules import DELETED_CODES, DIAGNOSTIC_CODES, HARD_CODES
from .types import OzonFlag, PipelineResult
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
) -> OzonFlag:
    if tier is None:
        if code in HARD_CODES:
            tier = "HARD"
        elif code in DIAGNOSTIC_CODES:
            tier = "DIAGNOSTIC"
        else:
            tier = "DIAGNOSTIC"
    if not group:
        if "SBP" in code or "PO_ID" in code:
            group = "identifier"
        elif "FONT" in code or "CID" in code or "CMAP" in code:
            group = "font"
        elif code.startswith("STREAM"):
            group = "stream"
        elif "TAG" in code or "BDC" in code:
            group = "tagged_pdf"
        else:
            group = "container"
    return OzonFlag(
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
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="OZ-CONT-009"))
        else:
            ingest_flag(result, _flag(code, detail, rule_id="OZ-CONT-001"))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0:
                tail = pdf_bytes[last_eof + 5:]
                if tail.strip(b"\r\n \t"):
                    ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="OZ-CONT-004"))
                else:
                    ingest_flag(result, _flag(
                        "OZON_EOF_EOL_ONLY",
                        "после %%EOF только EOL — штатно",
                        tier="DIAGNOSTIC",
                        rule_id="OZ-CONT-004",
                    ))
            continue
        if code in _DIAGNOSTIC_STRUCTURE:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="OZ-CONT-009"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, rule_id="OZ-CONT-003"))

    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", detail or "нарушена xref", rule_id="OZ-CONT-003"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="OZ-STRM-001"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC", rule_id="OZ-STRM-007"))


def _stage_active(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        if code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="HARD", rule_id="OZ-ACT-001"))


def _content_stream_edit(content: bytes) -> tuple[bool, str]:
    pad_comments = [
        ln for ln in content.split(b"\n")
        if ln.strip().startswith(b"%") and len(ln.strip()) > 12
    ]
    if pad_comments:
        return True, f"padding-комментарии ({len(pad_comments)} строк)"
    return False, ""


def _stage_content_ast(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("content_ast")
    content = content_stream_bytes(pdf_bytes) or b""
    if not content:
        return

    bt = len(re.findall(rb"\bBT\b", content))
    et = len(re.findall(rb"\bET\b", content))
    bdc = len(re.findall(rb"\bBDC\b", content))
    emc = len(re.findall(rb"\bEMC\b", content))
    q_ops = len(re.findall(rb"\bq\b", content))
    Q_ops = len(re.findall(rb"\bQ\b", content))
    result.stats["bt_et"] = {"bt": bt, "et": et, "bdc": bdc, "emc": emc}

    if bt != et:
        ingest_flag(result, _flag(
            "OZON_BT_ET_MISMATCH",
            f"несбалансированные BT/ET: {bt} vs {et}",
            tier="HARD",
            group="visibility",
            rule_id="OZ-VIS-001",
        ))
    elif q_ops != Q_ops:
        ingest_flag(result, _flag(
            "OZON_VIS_OPERATOR_DRIFT",
            f"q/Q drift {q_ops}/{Q_ops} — diagnostic",
            tier="DIAGNOSTIC",
            rule_id="OZ-VIS-009",
        ))

    if bdc != emc:
        ingest_flag(result, _flag(
            "OZON_BDC_EMC_MISMATCH",
            f"несбалансированные BDC/EMC: {bdc} vs {emc}",
            tier="HARD",
            group="tagged_pdf",
            rule_id="OZ-TAG-002",
        ))

    marked = b"/Marked" in pdf_bytes[:12000] and re.search(rb"/Marked\s+true", pdf_bytes[:12000])
    has_struct = b"/StructTreeRoot" in pdf_bytes
    if marked and not has_struct:
        ingest_flag(result, _flag(
            "OZON_TAG_STRUCT_MISSING",
            "Marked=true, но StructTreeRoot отсутствует",
            tier="HARD",
            group="tagged_pdf",
            rule_id="OZ-TAG-001",
        ))
    elif not marked and not has_struct:
        ingest_flag(result, _flag(
            "OZON_TAG_ABSENT",
            "без Tagged PDF — допустимо для future generator",
            tier="DIAGNOSTIC",
            rule_id="OZ-TAG-007",
        ))

    cs_fake, cs_detail = _content_stream_edit(content)
    if cs_fake:
        ingest_flag(result, _flag(
            "OZON_CONTENT_STREAM_EDIT", cs_detail,
            tier="HARD", group="visibility", rule_id="OZ-VIS-003",
        ))


def _stage_serializer_mix(
    pdf_bytes: bytes,
    result: PipelineResult,
    *,
    producer: str = "",
    creator: str = "",
) -> None:
    result.completed_checks.append("serializer_mix")
    mix = check_ozon_serializer_mix(pdf_bytes, producer=producer, creator=creator)
    result.stats["serializer_mix"] = mix.stats
    for sf in mix.flags:
        ingest_flag(result, _flag(
            sf.code, sf.detail,
            tier="HARD",
            group="stream",
            rule_id=sf.rule_id,
            expected=sf.expected,
            actual=sf.actual,
        ))


def _stage_skia_packing(
    pdf_bytes: bytes,
    result: PipelineResult,
    *,
    producer: str = "",
    creator: str = "",
) -> None:
    result.completed_checks.append("skia_packing")
    pack = check_ozon_skia_packing(pdf_bytes, producer=producer, creator=creator)
    result.stats["skia_packing"] = pack.stats
    for pf in pack.flags:
        ingest_flag(result, _flag(
            pf.code, pf.detail,
            tier="HARD",
            group="font",
            rule_id=pf.rule_id,
            expected=pf.expected,
            actual=pf.actual,
        ))


def _stage_fonts(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("fonts_cmap_glyph")
    forensic = run_pdf_forensics(pdf_bytes, bank="ozon", tier="universal")
    result.stats["forensics"] = forensic.stats

    _FONT_HARD = {
        "USED_CID_MISSING_FROM_CMAP", "CMAP_INVALID",
        "USED_CID_MISSING_FROM_W", "FONTFILE2_MISSING",
        "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
        "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
    }
    _SKIA_DIAG = {
        "W_ARRAY_PRETTY_PRINTED", "W_EXTRA_CID", "CMAP_W_MISMATCH",
        "GLYPH_COUNT_OUTLIER", "MISSING_WIDTH_TABLE",
    }

    for f in forensic.flags:
        if f.code in DELETED_CODES:
            continue
        if f.code in _SKIA_DIAG:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", rule_id="OZ-FONT-011"))
            continue
        if f.code in _FONT_HARD and f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", group="font", rule_id="OZ-FONT-002"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", rule_id="OZ-FONT-011"))


def _text_controls(text: str) -> OzonFlag | None:
    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        return _flag(
            "TEXT_LAYER_INCONSISTENT",
            f"невидимые управляющие символы ({', '.join(controls)})",
            tier="HARD",
            group="semantic",
            rule_id="OZ-SEM-001",
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
    result.stats["creator"] = creator

    if not is_ozon_receipt(text, pdf_bytes):
        result.not_ozon_receipt = True
        return

    family = classify_family(text)
    result.family = family
    result.stats["family"] = family
    result.stats["family_label"] = family_label(family)

    if generator == "unknown_coherent":
        result.new_coherent_profile = True
        ingest_flag(result, _flag(
            "OZON_NEW_PROFILE",
            f"новый generator path: «{producer[:60]}»",
            tier="DIAGNOSTIC",
            rule_id="OZ-META-001",
        ))
    else:
        ingest_flag(result, _flag(
            "OZON_GENERATOR_PATH",
            f"легитимный путь: {generator}",
            tier="DIAGNOSTIC",
            rule_id="OZ-META-001",
        ))

    ingest_flag(result, _flag(
        "OZON_FAMILY",
        f"семейство {family}: {family_label(family)}",
        tier="DIAGNOSTIC",
        rule_id="OZ-SEM-010",
    ))

    tc = _text_controls(text)
    if tc:
        ingest_flag(result, tc)

    nbsp_hits = find_trailing_nbsp_padding(text)
    if nbsp_hits:
        ingest_flag(result, _flag(
            NBSP_CODE, padding_detail(nbsp_hits),
            tier="HARD", group="semantic", rule_id="OZ-SEM-NBSP-001",
        ))

    bad, detail = check_total_arithmetic(text)
    if bad:
        ingest_flag(result, _flag(
            "OZON_TOTAL_ARITHMETIC_MISMATCH",
            detail,
            tier="HARD",
            group="semantic",
            rule_id="OZ-SEM-003",
        ))

    op_dt = parse_operation_datetime(text)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    creation_dt = _parse_pdf_date(creation_date)
    if creation_dt and op_dt and (op_dt - creation_dt).days > 30:
        ingest_flag(result, _flag(
            "OZON_META_CREATION_LATE",
            f"CreationDate на {(op_dt - creation_dt).days} дней раньше операции — export ambiguity",
            tier="DIAGNOSTIC",
            rule_id="OZ-META-002",
        ))

    if family in (FAMILY_SBP_OUT, FAMILY_SBP_IN):
        opid = extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        sbp = validate_ozon_sbp_receipt(
            opid or "", text, pdf_bytes,
            producer=producer, creator=creator,
        )
        result.stats["sbp_cipher"] = sbp.stats
        for cf in sbp.flags:
            # Policy: HARD_CODES / else DIAGNOSTIC_CODES / else HARD by default.
            if cf.code in DIAGNOSTIC_CODES:
                tier = "DIAGNOSTIC"
            else:
                tier = "HARD"
            ingest_flag(result, _flag(
                cf.code, cf.detail, tier=tier,
                group="identifier", rule_id=cf.rule_id,
                expected=cf.expected, actual=cf.actual,
            ))

        # Tail structure / known-fake / clock×tail composite (after universal SBP checks).
        if opid:
            has_universal_hard = bool(result.hard_flags)
            prov = validate_ozon_sbp_tail_provenance(
                opid,
                family=family,
                producer=producer,
                pdf_bytes=pdf_bytes,
                creation_date=creation_date,
                mod_date=mod_date,
                source_filename=result.stats.get("source_filename"),
            )
            result.stats["sbp_tail_provenance"] = prov.stats
            for tf in prov.flags:
                # If universal HARD already fired, keep only decisive provenance flags.
                if has_universal_hard and tf.tier not in ("KNOWN", "HARD"):
                    continue
                flag = _flag(
                    tf.code, tf.detail, tier=tf.tier,
                    group=tf.group or "identifier",
                    rule_id=tf.rule_id,
                    expected=tf.expected, actual=tf.actual,
                )
                if tf.raw_evidence:
                    flag.raw_evidence = tf.raw_evidence
                ingest_flag(result, flag)

    if family == FAMILY_CARD_OUT:
        po_id = extract_po_uuid(text)
        result.stats["po_uuid"] = po_id
        if not po_id:
            ingest_flag(result, _flag(
                "OZON_PO_ID_INVALID",
                "не найден po-UUID ID операции",
                tier="HARD",
                group="identifier",
                rule_id="OZ-ID-003",
            ))

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes,
        bank_key="ozon",
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
                group="cross_document", rule_id="OZ-XDOC-001",
            ))
        elif af.code == "PDF_MODDATE_EDITED":
            ingest_flag(result, _flag(af.code, af.detail, tier="DIAGNOSTIC"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", rule_id="OZ-VIS-005"))


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
        ("po_uuid", result.stats.get("po_uuid"), extract_po_uuid(t2)),
    ):
        if a and b and a != b:
            ingest_flag(result, _flag(
                "OZON_PARSER_PARITY_MISMATCH",
                f"{extractor}: parser A «{a}» ≠ parser B «{b}»",
                tier="HARD",
                group="parity",
                rule_id="OZ-PARSE-001",
                expected=str(a),
                actual=str(b),
            ))


def run_pipeline(
    pdf_bytes: bytes,
    file_hash: str,
    *,
    source_filename: str | None = None,
) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash)
    if source_filename:
        result.stats["source_filename"] = source_filename
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
    _stage_serializer_mix(pdf_bytes, result, producer=producer, creator=creator)
    _stage_skia_packing(pdf_bytes, result, producer=producer, creator=creator)
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
