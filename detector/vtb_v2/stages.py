"""VTB v2 pipeline stages."""

from __future__ import annotations

try:
    import fitz
except ImportError:
    fitz = None

from ..structure import (
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    xref_integrity,
)
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..vtb_profiles import detect_generator_path
from .account_sbp import check_account_sbp_profile
from .field_binding import check_field_value_binding
from .sbp import extract_sbp_opid, validate_sbp_id
from .shell_profile import check_sbp_shell_profile
from .signatures import check_known_signatures
from .subtypes import (
    check_method_hard_rules,
    check_required_fields_diagnostic,
    classify_subtype,
    is_vtb_receipt,
    subtype_label,
)
from .types import PipelineResult, VtbFlag
from .verdict import ingest_flag
from .rules import SUBTYPE_SBP, SUBTYPE_SBP_ACCOUNT

_MAX_BYTES = 8_000_000
_DIAG_STRUCTURE = frozenset({
    "MULTIPLE_EOF_PRESENT",
    "MULTIPLE_XREF_PRESENT",
    "PREV_TRAILER_PRESENT",
    "INCREMENTAL_UPDATE_PRESENT",
    "MULTIPLE_STARTXREF_PRESENT",
    "DUPLICATE_ACTIVE_OBJECT_DEFINITION",
})


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


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str]:
    if not fitz:
        return "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        m = doc.metadata or {}
        doc.close()
        return m.get("producer") or "", m.get("creator") or "", m.get("creationDate") or ""
    except Exception:
        return "", "", ""


def _ingest(result: PipelineResult, flags: list[VtbFlag]) -> None:
    for flag in flags:
        ingest_flag(result, flag)


def run_pipeline(pdf_bytes: bytes, file_hash: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash, profile_version="vtb_openhtml_v1")
    try:
        result.completed_checks.append("intake")
        result.stats["size"] = len(pdf_bytes)
        if not pdf_bytes:
            result.analysis_complete = False
            return result
        if len(pdf_bytes) > _MAX_BYTES:
            result.analysis_complete = False
            result.stats["budget_exceeded"] = True
            return result
        if b"/Encrypt" in pdf_bytes[:8000]:
            result.analysis_complete = False
            result.stats["encrypted"] = True
            return result

        text = _pdf_text(pdf_bytes)
        producer, creator, creation_date = _pdf_metadata(pdf_bytes)
        result.generator_path = detect_generator_path(producer, creator)
        result.stats["producer"] = producer
        result.stats["creator"] = creator
        result.stats["creation_date"] = creation_date
        result.stats["text_len"] = len(text or "")

        # Routing before scoring
        result.completed_checks.append("subtype_routing")
        if not is_vtb_receipt(text, pdf_bytes):
            result.not_vtb_receipt = True
            result.completed_checks.append("pipeline_complete")
            return result

        subtype = classify_subtype(text)
        result.subtype = subtype
        result.stats["subtype"] = subtype
        result.stats["subtype_label"] = subtype_label(subtype)
        if subtype == "vtb_unknown_coherent":
            result.new_coherent_profile = True

        # Lightweight container / active (HARD only on real breaks)
        result.completed_checks.append("container")
        s1 = validate_pdf_structure(pdf_bytes)
        for code, detail in zip(s1.codes, s1.details):
            if code in _DIAG_STRUCTURE:
                ingest_flag(result, VtbFlag(code, detail, tier="DIAGNOSTIC"))
            elif code in (
                "PDF_STRUCTURE_INVALID",
                "XREF_OFFSET_INVALID",
                "TRAILER_INVALID",
                "MULTIPLE_PDF_HEADERS",
                "STREAM_DECOMPRESSION_FAILED",
                "STREAM_LENGTH_MISMATCH",
            ):
                ingest_flag(result, VtbFlag(code, detail, tier="HARD"))
            else:
                ingest_flag(result, VtbFlag(code, detail, tier="DIAGNOSTIC"))

        broken, detail = xref_integrity(pdf_bytes)
        if broken:
            ingest_flag(result, VtbFlag(
                "XREF_OFFSET_INVALID", detail or "нарушена xref", tier="HARD",
            ))

        s2 = validate_incremental_updates(pdf_bytes)
        for code, detail in zip(s2.codes, s2.details):
            if code == "TRAILING_DATA_AFTER_EOF":
                last = pdf_bytes.rfind(b"%%EOF")
                tail = pdf_bytes[last + 5:] if last >= 0 else b""
                if tail.strip(b"\r\n \t"):
                    ingest_flag(result, VtbFlag(code, detail, tier="HARD"))
                else:
                    ingest_flag(result, VtbFlag(
                        "VTB_EOF_EOL_ONLY", "после %%EOF только EOL",
                        tier="DIAGNOSTIC",
                    ))
            elif code in _DIAG_STRUCTURE:
                ingest_flag(result, VtbFlag(code, detail, tier="DIAGNOSTIC"))

        act = validate_active_content(pdf_bytes)
        for code, detail in zip(act.codes, act.details):
            ingest_flag(result, VtbFlag(code, detail, tier="HARD", group="active"))

        # Method HARD rules
        result.completed_checks.append("method_fieldset")
        _ingest(result, check_method_hard_rules(
            text, subtype=subtype, profile_version=result.profile_version,
        ))
        _ingest(result, check_required_fields_diagnostic(text, subtype))
        _ingest(result, check_field_value_binding(text))
        nbsp_hits = find_trailing_nbsp_padding(text)
        if nbsp_hits:
            ingest_flag(result, VtbFlag(
                NBSP_CODE, padding_detail(nbsp_hits),
                tier="HARD", group="fields", rule_id=NBSP_CODE,
            ))

        # SBP parser + known linked/tail
        sbp_known = False
        if subtype in {SUBTYPE_SBP, SUBTYPE_SBP_ACCOUNT} or extract_sbp_opid(text):
            result.completed_checks.append("sbp_id")
            opid = extract_sbp_opid(text)
            op_dt = None
            if subtype == SUBTYPE_SBP_ACCOUNT and creation_date:
                from ..bank_spec_engine import _pdf_creation_as_msk
                op_dt = _pdf_creation_as_msk(creation_date)
            sbp = validate_sbp_id(
                opid, text, subtype=subtype, operation_dt=op_dt,
            )
            result.stats["sbp"] = sbp.stats
            sbp_known = sbp.known_fake_hit
            _ingest(result, sbp.flags)

        # File / semantic / assembly known-fake channels
        result.completed_checks.append("known_signatures")
        sig = check_known_signatures(
            pdf_bytes, text, file_hash=file_hash, sbp_known_hit=sbp_known,
        )
        result.stats["signatures"] = {
            k: v for k, v in sig.stats.items() if k != "assembly_components"
        }
        result.stats["assembly_components"] = sig.stats.get("assembly_components")
        _ingest(result, sig.flags)

        # openhtml SBP shell packing (CID /W runs floor) — structural HARD
        result.completed_checks.append("shell_profile")
        shell = check_sbp_shell_profile(
            pdf_bytes,
            subtype=subtype,
            generator_path=result.generator_path,
        )
        result.stats["shell_profile"] = shell.stats
        _ingest(result, shell.flags)

        result.completed_checks.append("account_sbp")
        account = check_account_sbp_profile(
            pdf_bytes, text, producer=producer, subtype=subtype,
        )
        result.stats["account_sbp"] = account.stats
        _ingest(result, account.flags)

        # Native generator path is diagnostic only.
        if "openhtmltopdf" in (producer or "").lower():
            ingest_flag(result, VtbFlag(
                "VTB_GENERATOR_PATH",
                "Producer openhtmltopdf.com — штатный путь ВТБ",
                tier="DIAGNOSTIC",
            ))
        elif (producer or "").lower().startswith("openpdf 2."):
            ingest_flag(result, VtbFlag(
                "VTB_GENERATOR_PATH",
                "Producer OpenPDF 2.x — штатный путь СБП на счёт ВТБ",
                tier="DIAGNOSTIC",
            ))

        result.completed_checks.append("pipeline_complete")
    except Exception as exc:
        result.analysis_complete = False
        result.stats["pipeline_error"] = str(exc)[:300]
    return result
