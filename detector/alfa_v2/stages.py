"""Production Alfa v2 pipeline."""

from __future__ import annotations

import re

try:
    import fitz
except ImportError:
    fitz = None

from ..structure import (
    content_stream_bytes,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .content import check_content
from .file_size import check_file_size
from .fonts import check_fonts
from .identity import extract_and_check_identity
from .profile_semantics import (
    EmitterEvidence,
    classify_submethod,
    extract_operation_datetime,
    extract_operation_ids,
    parse_amounts,
    run_semantic_checks,
)
from .rules import SUPPORTING_GROUPS, classify_code
from .sbp import validate_sbp_text
from .shell_clone import check_shell_clone
from .static_assets import check_static_assets
from .streams import check_streams
from .types import AlfaFlag, PipelineResult
from .unconfirmed_profiles import check_new_sbp_profile
from .verdict import ingest_flag


_MAX_BYTES = 8_000_000
_ALFA_MARKERS = (
    "квитанция о переводе",
    "альфа-банк",
    "alfa-bank",
    "сформирована",
)


def _flag(
    code: str,
    detail: str,
    *,
    tier: str = "",
    group: str = "",
    rule_id: str = "",
) -> AlfaFlag:
    classification = classify_code(code)
    if not tier:
        tier = {
            "KNOWN": "KNOWN",
            "HARD": "HARD",
            "B": "B",
        }.get(classification, "IGNORE")
    return AlfaFlag(
        code=code,
        detail=detail,
        tier=tier,
        group=group or SUPPORTING_GROUPS.get(code, ""),
        rule_id=rule_id or code,
    )


def _pdf_context(pdf_bytes: bytes) -> tuple[str, dict]:
    if not fitz:
        return "", {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        metadata = dict(doc.metadata or {})
        metadata["page_count"] = doc.page_count
        doc.close()
        return text, metadata
    except Exception as exc:
        return "", {"error": type(exc).__name__}


def _is_alfa_receipt(text: str, pdf_bytes: bytes, producer: str = "") -> bool:
    """Accept Oracle/Quartz Alfa shells even when glyph transplant corrupts text."""
    low = (text or "").lower()
    pr = (producer or "").lower()
    if sum(marker in low for marker in _ALFA_MARKERS) >= 2:
        return True
    oracle_or_quartz = (
        "oracle bi publisher" in pr
        or "quartz pdfcontext" in pr
        or b"oracle bi publisher" in pdf_bytes.lower()
        or b"quartz pdfcontext" in pdf_bytes.lower()
    )
    if oracle_or_quartz and (
        "сформирована" in low
        or "квитанция" in low
        or "сбп" in low
        or "номер операции" in low
        or re.search(r"(?<![A-Z0-9])[CZ]\d{15}(?![A-Z0-9])", (text or "").upper())
    ):
        return True
    return oracle_or_quartz and bool(re.search(rb"/ID\s*\[\s*<[0-9A-Fa-f]+>", pdf_bytes))


def _ingest_structure(result: PipelineResult, check, name: str) -> None:
    result.stats[name] = check.stats
    for code, detail in zip(check.codes, check.details):
        ingest_flag(result, _flag(code, detail))


def _ingest_external(result: PipelineResult, external) -> None:
    for flag in getattr(external, "flags", ()):
        ingest_flag(result, _flag(
            flag.code,
            flag.detail,
            tier=getattr(flag, "tier", ""),
            group=getattr(flag, "group", ""),
            rule_id=getattr(flag, "rule_id", "") or flag.code,
        ))
    for flag in getattr(external, "diagnostics", ()):
        ingest_flag(result, _flag(
            flag.code,
            flag.detail,
            tier="IGNORE" if getattr(flag, "tier", "") == "DIAGNOSTIC" else getattr(flag, "tier", ""),
            group=getattr(flag, "group", ""),
        ))


def _emitter_evidence(pdf_bytes: bytes, metadata: dict) -> EmitterEvidence:
    version_match = re.match(rb"%PDF-(\d\.\d)", pdf_bytes)
    version = version_match.group(1).decode("ascii") if version_match else ""
    object_count = len(re.findall(rb"(?m)^\s*\d+\s+\d+\s+obj\b", pdf_bytes))
    low = pdf_bytes.lower()
    if object_count == 16:
        graph_hint = "oracle"
    elif object_count == 18:
        graph_hint = "quartz"
    else:
        graph_hint = ""
    if b"+tahoma" in low and b"/f1" in low:
        resources_hint = "oracle"
    elif b"font000000" in low or b"/g1" in low:
        resources_hint = "quartz"
    else:
        resources_hint = ""
    return EmitterEvidence(
        producer=str(metadata.get("producer") or ""),
        pdf_version=version,
        object_count=object_count,
        object_graph_hint=graph_hint,
        resources_hint=resources_hint,
        icc_profile="/ICCBased" if b"/ICCBased" in pdf_bytes else "",
        icc_hint="quartz" if b"/ICCBased" in pdf_bytes else "",
    )


def run_pipeline(pdf_bytes: bytes, file_hash: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash)
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes or len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False
        result.stats["intake_error"] = "empty" if not pdf_bytes else "file_size"
        return result

    result.completed_checks.append("container")
    _ingest_structure(result, validate_pdf_structure(pdf_bytes), "pdf_structure")
    _ingest_structure(result, validate_incremental_updates(pdf_bytes), "incremental_updates")
    broken_xref, xref_detail = xref_integrity(pdf_bytes)
    result.stats["xref"] = {"broken": broken_xref, "detail": xref_detail}
    if broken_xref:
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", xref_detail))

    result.completed_checks.append("streams_active")
    _ingest_structure(result, validate_stream_compression(pdf_bytes), "stream_compression")
    _ingest_structure(result, validate_active_content(pdf_bytes), "active_content")

    text, metadata = _pdf_context(pdf_bytes)
    result.stats["metadata"] = metadata
    if not fitz or metadata.get("error"):
        result.analysis_complete = False
        result.stats["text_extraction_error"] = metadata.get("error", "fitz_missing")
        return result
    if not _is_alfa_receipt(
        text,
        pdf_bytes,
        producer=str(metadata.get("producer") or ""),
    ):
        result.not_alfa_receipt = True
        return result

    evidence = _emitter_evidence(pdf_bytes, metadata)
    method = classify_submethod(text)
    result.channel = method
    result.receipt_subtype = method
    result.generator_path = (
        "oracle_bi"
        if "oracle" in evidence.producer.lower()
        else "quartz_ios"
        if "quartz" in evidence.producer.lower()
        else "unknown"
    )
    result.stats["receipt_subtype_label"] = {
        "sbp": "СБП Альфа-Банк",
        "card": "Альфа-Банк, с карты на карту",
        "phone": "Альфа-Банк, клиенту по телефону",
    }.get(method, "Квитанция Альфа-Банка")

    fs = check_file_size(
        pdf_bytes,
        producer=str(metadata.get("producer") or evidence.producer or ""),
        generator_path=result.generator_path or "",
    )
    result.stats["file_size_check"] = fs.stats
    for flag in fs.flags:
        ingest_flag(result, flag)
    result.completed_checks.append("file_size")

    result.completed_checks.append("profile_semantics")
    semantics = run_semantic_checks(text, evidence)
    result.stats["semantics"] = semantics.stats
    _ingest_external(result, semantics)
    if method == "sbp":
        sbp = validate_sbp_text(text)
        result.stats["sbp"] = sbp.stats
        _ingest_external(result, sbp)

    result.completed_checks.append("serializer_assets")
    streams = check_streams(
        pdf_bytes,
        producer=str(metadata.get("producer") or ""),
    )
    result.stats["serializer"] = streams.stats
    _ingest_external(result, streams)
    full_foreign = any(
        flag.code == "ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH"
        for flag in streams.flags
    )
    synthetic_embed = bool(
        (semantics.stats or {}).get("synthetic_operation_number_time_embedding")
    )
    if full_foreign and synthetic_embed:
        ingest_flag(
            result,
            _flag(
                "ALFA_KNOWN_GENERATOR_FULL_RESERIALIZATION",
                "known generator: exact Oracle BI shell with 0/6 Java Deflater(6) "
                "streams plus C16+DDMMYY+HHMMSS operation-number time embedding",
                tier="KNOWN",
            ),
        )
    rebuild_proven = any(
        flag.code in {
            "ALFA_MIXED_SERIALIZER_PROVENANCE",
            "ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE",
            "ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH",
        }
        for flag in streams.flags
    )
    assets = check_static_assets(
        pdf_bytes,
        producer=str(metadata.get("producer") or ""),
        document_rebuild_proven=rebuild_proven,
    )
    result.stats["static_assets"] = assets.stats
    _ingest_external(result, assets)

    result.completed_checks.append("shell_clone")
    shell = check_shell_clone(
        pdf_bytes,
        text,
        file_hash=file_hash,
        producer=str(metadata.get("producer") or ""),
    )
    result.stats["shell_clone"] = shell.stats
    _ingest_external(result, shell)

    result.completed_checks.append("content_fonts")
    content = check_content(
        pdf_bytes,
        producer=str(metadata.get("producer") or ""),
    )
    result.stats["content"] = content.stats
    _ingest_external(result, content)
    fonts = check_fonts(
        pdf_bytes,
        producer=str(metadata.get("producer") or ""),
    )
    result.stats["fonts"] = fonts.stats
    _ingest_external(result, fonts)

    result.completed_checks.append("embedded_font_reassembly_forensics")
    from ..embedded_font_reassembly import check_embedded_font_reassembly
    rebuild = check_embedded_font_reassembly(
        pdf_bytes,
        bank="alfa",
        producer=str(metadata.get("producer") or ""),
        creator=str(metadata.get("creator") or ""),
    )
    result.stats["embedded_font_reassembly"] = rebuild.stats
    _ingest_external(result, rebuild)
    if not rebuild.analysis_ok:
        result.analysis_complete = False

    result.completed_checks.append("cross_document_identity")
    amounts = parse_amounts(text)
    operation_dt = extract_operation_datetime(text)
    operation_ids = extract_operation_ids(text)
    identity = extract_and_check_identity(
        text,
        file_id=file_hash,
        pdf_bytes=pdf_bytes,
        submethod=method,
        parsed={
            "operation_id": operation_ids[0] if operation_ids else "",
            "amount": str(amounts.amount) if amounts.amount is not None else "",
            "fee": str(amounts.fee) if amounts.fee is not None else "",
            "operation_date": (
                operation_dt.strftime("%d.%m.%Y %H:%M:%S")
                if operation_dt
                else ""
            ),
        },
    )
    result.stats["identity"] = identity.stats.as_dict()
    if identity.conflict:
        result.cross_document_identity_conflict = True
    _ingest_external(result, identity)

    result.completed_checks.append("new_sbp_profile")
    new_sbp = check_new_sbp_profile(
        pdf_bytes,
        text,
        producer=str(metadata.get("producer") or ""),
        creation_date=str(metadata.get("creationDate") or ""),
        file_hash=file_hash,
    )
    result.stats["new_sbp_profile"] = new_sbp.stats
    # Unknown bank5/suffix is observational only — never forces MANUAL/UNKNOWN.
    for flag in new_sbp.flags:
        ingest_flag(result, flag)

    result.stats["content_decoded_length"] = len(content_stream_bytes(pdf_bytes) or b"")
    result.completed_checks.append("complete")
    return result
