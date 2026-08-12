"""Sber v2 full pipeline stages."""

from __future__ import annotations

try:
    import fitz
except ImportError:
    fitz = None

from ..sber_profiles import (
    classify_submethod,
    detect_generator_path,
    is_sber_receipt,
)
from .container import check_xref_object_graph
from .content import check_content_grammar
from .cross_document import (
    check_cross_document_identity,
    check_reassembled_bank_assets,
)
from .file_size import check_file_size
from .fonts import check_font_contamination
from .geometry import check_label_value_geometry
from .glyph_spacing import check_glyph_spacing
from .overlay import check_overlay_hidden_text
from .parity import check_dual_parser_parity
from .profile_gates import is_new_coherent_profile
from .rules import LEGACY_TO_PROFILE, PROFILE_LABELS
from .sbp_exact_profile import check_sbp_exact_profile
from .semantics import (
    check_legacy_document,
    check_sbp_linked_tuple,
    check_semantic_tuples,
)
from .streams import check_stream_integrity
from .types import PipelineResult, SberFlag
from .verdict import distinct_supporting_groups, ingest_flag

_MAX_BYTES = 8_000_000


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


def _ingest_all(result: PipelineResult, flags: list[SberFlag]) -> None:
    for flag in flags:
        ingest_flag(result, flag)


def _stage_intake(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes:
        result.analysis_complete = False
        result.stats["empty"] = True
    elif len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False
        result.stats["budget_exceeded"] = "file_size"
    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_classify(pdf_bytes: bytes, text: str, result: PipelineResult,
                    producer: str, creator: str) -> None:
    result.completed_checks.append("classify")
    generator = detect_generator_path(producer, creator)
    result.generator_path = generator
    result.stats["generator_path"] = generator
    result.stats["producer"] = producer
    result.stats["creator"] = creator
    result.stats["text_len"] = len(text or "")

    if not is_sber_receipt(text, pdf_bytes):
        result.not_sber_receipt = True
        result.completed_checks.append("is_sber_receipt")
        return
    result.completed_checks.append("is_sber_receipt")

    legacy = classify_submethod(text, producer=producer, creator=creator)
    profile_id = LEGACY_TO_PROFILE.get(legacy, "")
    if not profile_id or is_new_coherent_profile(profile_id or "unknown", generator):
        if not profile_id:
            profile_id = "unknown_coherent" if generator == "unknown_coherent" else "unknown"
            result.new_coherent_profile = True

    result.profile_id = profile_id
    result.submethod = legacy
    result.stats["submethod"] = legacy
    result.stats["profile_id"] = profile_id
    result.stats["submethod_label"] = PROFILE_LABELS.get(profile_id, legacy or profile_id)


def run_pipeline(pdf_bytes: bytes, file_hash: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash)
    try:
        _stage_intake(pdf_bytes, result)
        if not result.analysis_complete:
            return result

        text = _pdf_text(pdf_bytes)
        producer, creator, creation, mod = _pdf_metadata(pdf_bytes)
        result.stats["creation_date"] = creation
        result.stats["mod_date"] = mod

        _stage_classify(pdf_bytes, text, result, producer, creator)
        if result.not_sber_receipt:
            result.completed_checks.append("pipeline_complete")
            return result

        # File weight vs genuine profile envelope (strong Δ → HARD / soft → B)
        fs = check_file_size(pdf_bytes, profile_id=result.profile_id or "")
        result.stats["file_size_check"] = fs.stats
        _ingest_all(result, fs.flags)
        result.completed_checks.append("file_size")

        # Phase 3 — container / streams / grammar
        xref = check_xref_object_graph(pdf_bytes)
        result.stats["xref"] = xref.stats
        _ingest_all(result, xref.flags)
        if not xref.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("xref_object_graph")

        streams = check_stream_integrity(pdf_bytes)
        result.stats["streams"] = streams.stats
        _ingest_all(result, streams.flags)
        if not streams.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("stream_integrity")

        grammar = check_content_grammar(pdf_bytes, profile_id=result.profile_id)
        result.stats["content"] = grammar.stats
        _ingest_all(result, grammar.flags)
        if not grammar.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("content_grammar")

        # Phase 4 — dual parser / overlay / geometry
        parity = check_dual_parser_parity(pdf_bytes, text)
        result.stats["parity"] = parity.stats
        _ingest_all(result, parity.flags)
        if not parity.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("dual_parser_parity")

        overlay = check_overlay_hidden_text(pdf_bytes)
        result.stats["overlay"] = overlay.stats
        _ingest_all(result, overlay.flags)
        if not overlay.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("overlay_hidden_text")

        geometry = check_label_value_geometry(
            pdf_bytes, text, profile_id=result.profile_id,
        )
        result.stats["geometry"] = geometry.stats
        _ingest_all(result, geometry.flags)
        if not geometry.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("label_value_geometry")

        # Phase 5 — fonts / exact SBP profile HARDs / semantics
        fonts = check_font_contamination(
            pdf_bytes, producer=producer, creator=creator,
            profile_id=result.profile_id,
        )
        result.stats["fonts"] = fonts.stats
        _ingest_all(result, fonts.flags)
        if not fonts.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("font_contamination")

        spacing = check_glyph_spacing(
            pdf_bytes,
            producer=producer,
            profile_id=result.profile_id or "",
        )
        result.stats["glyph_spacing"] = spacing.stats
        _ingest_all(result, spacing.flags)
        if not spacing.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("glyph_spacing")

        exact = check_sbp_exact_profile(
            pdf_bytes,
            profile_id=result.profile_id,
            generator_path=result.generator_path,
            creator=creator,
            producer=producer,
        )
        result.stats["sbp_exact_profile"] = exact.stats
        # Near-miss (known sbp_outgoing + Jasper, but new page/skeleton vs tiny atlas)
        # must NOT become «НЕИЗВЕСТНЫЙ ДОКУМЕНТ» — that confuses users when the
        # issuer is clearly Сбер. Exact HARDs stay skipped; other rules still run.
        if exact.near_miss_unknown:
            result.stats["sbp_exact_near_miss"] = True
            result.ignored_observations.append(
                "[SBER_SBP_EXACT_NEAR_MISS] sbp_outgoing/jasper вне точного "
                "atlas-контракта — exact HARD пропущены, банк всё ещё Сбер"
            )
        _ingest_all(result, exact.flags)
        if not exact.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("sbp_exact_profile")

        result.completed_checks.append("embedded_font_reassembly_forensics")
        from ..embedded_font_reassembly import check_embedded_font_reassembly
        rebuild = check_embedded_font_reassembly(
            pdf_bytes,
            bank="sber",
            producer=producer,
            creator=creator,
            profile_id=result.profile_id or "",
        )
        result.stats["embedded_font_reassembly"] = rebuild.stats
        for rf in rebuild.flags:
            ingest_flag(result, SberFlag(
                code=rf.code,
                detail=rf.detail,
                tier=rf.tier,
                group=rf.group,
                rule_id=rf.rule_id or rf.code,
            ))
        if not rebuild.analysis_ok:
            result.analysis_complete = False

        dual_miss = bool(geometry.missing_required) and not any(
            parity.stats.get(f"{k}_fitz")
            for k in ("sbp_id", "legacy_doc", "internal_doc")
        )
        sem = check_semantic_tuples(
            text, profile_id=result.profile_id, dual_parser_missed=dual_miss,
        )
        result.stats["semantics"] = sem.stats
        _ingest_all(result, sem.flags)
        if not sem.analysis_ok:
            result.analysis_complete = False

        sbp = check_sbp_linked_tuple(text, profile_id=result.profile_id)
        result.stats["sbp"] = sbp.stats
        _ingest_all(result, sbp.flags)
        if not sbp.analysis_ok:
            result.analysis_complete = False

        legacy = check_legacy_document(text, profile_id=result.profile_id)
        result.stats["legacy"] = legacy.stats
        _ingest_all(result, legacy.flags)
        result.completed_checks.append("semantic_sbp")

        # Phase 6 — cross-doc / reassembled
        groups_so_far = distinct_supporting_groups(result.supporting_flags)
        xdoc = check_cross_document_identity(
            pdf_bytes, text, file_hash=file_hash, profile_id=result.profile_id,
        )
        result.stats["cross_document"] = xdoc.stats
        _ingest_all(result, xdoc.flags)
        if xdoc.identity_conflict:
            result.cross_document_identity_conflict = True
        if not xdoc.analysis_ok:
            result.analysis_complete = False
        result.completed_checks.append("cross_document_identity")

        reassembled = check_reassembled_bank_assets(
            pdf_bytes,
            profile_id=result.profile_id,
            extra_forensic_groups=groups_so_far,
        )
        result.stats["reassembled"] = reassembled.stats
        _ingest_all(result, reassembled.flags)
        result.completed_checks.append("reassembled_assets")

        result.completed_checks.append("pipeline_complete")
    except Exception as exc:
        result.analysis_complete = False
        result.stats["pipeline_error"] = str(exc)[:300]
    return result
