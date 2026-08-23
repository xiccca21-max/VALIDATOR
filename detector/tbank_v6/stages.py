"""v6.0 eight-stage T-Bank pipeline (spec sections 4–13)."""

from __future__ import annotations

import re

try:
    import fitz
except ImportError:
    fitz = None

from ..anti_edit import run_checks as run_anti_edit_checks
from ..corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    detect_receipt_channel,
    detect_receipt_subtype,
    receipt_subtype_label,
)
from ..pdf_forensics import Weight, run_pdf_forensics
from ..sbp_cipher import extract_receipt_datetime, extract_sbp_opid
from ..tbank_deflate_profile import check_deflate_profile
from ..tbank_font_cid_closure import check_font_cid_closure
from ..tbank_glyph_atlas import check_tbank_glyph_atlas
from ..tbank_glyph_slot_transplant import check_glyph_slot_transplant
from ..tbank_used_glyph_integrity import check_tbank_used_glyph_integrity
from ..tbank_font_table_integrity import check_font_table_integrity
from ..tbank_sfnt_table_integrity import check_tbank_sfnt_table_inventory
from ..tbank_notdef_integrity import check_tbank_notdef_integrity
from ..tbank_f1_orphan_glyph import check_tbank_f1_orphan_glyph
from ..tbank_id_reuse import check_trailer_id_reuse
from ..tbank_info_keywords_lex import check_info_keywords_lex
from ..tbank_keywords_generation import check_keywords_generation
from ..tbank_receipt_format import check_receipt_format
from ..tbank_reassembled_subset import check_reassembled_bank_assets
from ..tbank_reassembly_family_v3 import (
    check_tbank_f1_maxp_recomputed_to_subset,
    check_tbank_subset_orphan_residue,
    run_tbank_reassembly_family_v3_stack,
)
from .emitter_invariants import check_tbank_emitter_invariants
from ..tbank_serializer_families_v1 import check_tbank_serializer_families_v1
from ..tbank_sbp_content import validate_tbank_sbp_id
from ..tbank_sbp_epoch_reuse import check_sbp_epoch_and_receipt_stem
from ..tbank_spec import check_foreign_producer
from ..tbank_jasper_profile import claims_confirmed_tbank_profile
from ..tbank_stream_integrity import check_stream_integrity
from ..tbank_text_layout_fingerprint import check_tbank_layout_fingerprint
from ..field_edge_alignment import check_tbank_value_right_edge
from .sbp_competitor_hard import check_sbp_competitor_hard
from ..structure import (
    content_skeleton_hash,
    content_stream_bytes,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .file_size import check_file_size
from .fontfile2_size import check_fontfile2_size
from .f1_subset_shape import check_f1_subset_shape
from .f2_subset_shape import check_f2_subset_shape
from .basefont_subset_cogen import check_basefont_subset_cogen
from .glyph_spacing import check_glyph_spacing
from .content_profile import check_content_profile
from .known_signatures import check_k_font_001, check_k_font_002
from .rules import HARD_CODES, IGNORED_CODES, KNOWN_GENERATOR_SKELETONS, SUPPORTING_GROUPS
from .types import PipelineResult, V6Flag
from .verdict import ingest_flag

_MAX_BYTES = 8_000_000
_BAD_TEXT_CONTROLS = {
    "\x00": "NUL",
    "\u2000": "en quad",
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
    "\u2066": "bidi isolate",
    "\u2067": "bidi isolate",
    "\u2068": "bidi isolate",
    "\u2069": "bidi isolate",
}
# OpenPDF genuines: «Квитанция  № N-NNN-NNN-NNN-NNN» with empty trailing.
# SEQ rebuilds append dagger/combining/NUL garbage after the digits.
_RECEIPT_ID_RE = re.compile(
    r"Квитанция\s+№\s+(\d(?:-\d{3}){4})([^\n]*)",
)
_LATIN_HOMOGLYPHS = str.maketrans({
    "A": "А", "a": "а", "B": "В", "C": "С", "c": "с", "E": "Е",
    "e": "е", "H": "Н", "K": "К", "M": "М", "O": "О", "o": "о",
    "P": "Р", "p": "р", "T": "Т", "X": "Х", "x": "х", "Y": "У", "y": "у",
})
_CORE_RU_LABELS = frozenset({
    "Получатель", "Отправитель", "Комиссия", "Сумма", "Итого",
    "Телефон", "Карта", "Банк", "Статус", "Успешно", "Квитанция", "Перевод",
})
_COMPACT_AMOUNT_RE = re.compile(r"(?<!\d)\d{5,}₽")
_PHONE_FMT_RE = re.compile(r"^\+7 \(\d{3}\) \d{3}-\d{2}-\d{2}$")
_TBANK_SUBJECT = b"/reports/IB/Receipt"
_CREATION_RE = re.compile(
    rb"/CreationDate\s*\(([^)]*)\)|/CreationDate\s*<([^>]*)>"
)
_MODDATE_RE = re.compile(
    rb"/ModDate\s*\(([^)]*)\)|/ModDate\s*<([^>]*)>"
)


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _meta_string(pdf_bytes: bytes, pattern: re.Pattern[bytes]) -> str:
    m = pattern.search(pdf_bytes)
    if not m:
        return ""
    raw = m.group(1) or m.group(2) or b""
    return raw.decode("latin1", "replace").strip()


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str]:
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            meta = doc.metadata or {}
            doc.close()
            return (
                meta.get("producer") or "",
                meta.get("creator") or "",
                meta.get("creationDate") or "",
                meta.get("modDate") or "",
            )
        except Exception:
            pass
    return ("", "", "", "")


def _pdf_text_and_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str, str]:
    """Single fitz open for text + Info dict (avoids a second parse in the pipeline)."""
    if not fitz:
        return "", "", "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        meta = doc.metadata or {}
        doc.close()
        return (
            text,
            meta.get("producer") or "",
            meta.get("creator") or "",
            meta.get("creationDate") or "",
            meta.get("modDate") or "",
        )
    except Exception:
        return "", "", "", "", ""


def _has_decisive(result: PipelineResult) -> bool:
    """HARD/KNOWN already decide ФЕЙК — remaining stages cannot clear the verdict."""
    return bool(
        result.hard_flags
        or result.known_fake_flags
        or result.not_a_tbank_receipt
        or result.cross_document_identity_conflict
    )

def _v6_flag(
    code: str,
    detail: str,
    *,
    tier: str | None = None,
    rule_id: str = "",
) -> V6Flag:
    if tier is None:
        if code in HARD_CODES:
            tier = "A"
        elif code in SUPPORTING_GROUPS:
            tier = "B"
        elif code in IGNORED_CODES:
            tier = "IGNORE"
        else:
            tier = "A"
    group = SUPPORTING_GROUPS.get(code, "")
    if tier == "KNOWN" and not group:
        group = "known_malicious_signature"
    if tier == "A" and not group:
        if code in (
            "TBANK_KEYWORDS_GENERATION_MISMATCH",
            "TBANK_INFO_KEYWORDS_LEX_MISMATCH",
            "TBANK_RECEIPT_NUMBER_FORMAT",
            "TBANK_TRAILER_ID_REUSED",
        ):
            group = "B6_metadata_version"
        elif code.startswith("SBP_") or code.startswith("TBANK_SBP_") or code.startswith("TBANK_KEYWORDS_") or code.startswith("FIELD_"):
            group = "semantic_and_identity"
        elif code.startswith("TBANK_CONTENT") or code.startswith("TBANK_BT"):
            group = "content_and_visual_evasion"
        elif code == "TBANK_TEXT_LAYOUT_FINGERPRINT":
            group = "content_grammar_layout"
        elif "FONT" in code or "CID" in code or "CMAP" in code or "GLYPH" in code:
            group = "font_cmap_glyph"
        elif code.startswith("STREAM_") or code == "UNEXPECTED_STREAM_FILTER":
            group = "stream_integrity_and_dos"
        elif "JAVASCRIPT" in code or "ACTIVE" in code or "EMBEDDED" in code:
            group = "active_or_hidden_content"
        else:
            group = "container_ambiguity_and_corruption"
    return V6Flag(
        code=code, detail=detail, tier=tier, group=group,
        rule_id=rule_id or code,
    )


def _stage_internal_serialization(
    pdf_bytes: bytes,
    text: str,
    result: PipelineResult,
    *,
    producer: str = "",
    creator: str = "",
    file_hash: str = "",
) -> None:
    """K-TBANK-DEFLATE/STREAM/FONT/CID/RECEIPT/ID-REUSE hard serialization checks."""
    result.completed_checks.append("internal_serialization")
    if not _is_tbank_receipt(pdf_bytes, text):
        return

    dp = check_deflate_profile(pdf_bytes, text=text, producer=producer, creator=creator)
    result.stats["deflate_profile"] = dp.stats
    result.stats["flate_profiles"] = [
        {"object": p.object_number, "role": p.role.value, "canonical": p.canonical_match}
        for p in dp.profiles
    ]
    for f in dp.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    si = check_stream_integrity(
        pdf_bytes, producer=producer, creator=creator, profiles=dp.profiles or None,
    )
    result.stats["stream_integrity"] = si.stats
    for f in si.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    cc = check_font_cid_closure(pdf_bytes, producer=producer, creator=creator)
    result.stats["font_cid_closure"] = cc.stats
    for f in cc.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    ft = check_font_table_integrity(pdf_bytes, producer=producer, creator=creator)
    result.stats["font_table_integrity"] = ft.stats
    for f in ft.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    result.completed_checks.append("f1_orphan_simple_glyph")
    orphan = check_tbank_f1_orphan_glyph(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    result.stats["f1_orphan_simple_glyph"] = orphan.stats
    for of in orphan.flags:
        ingest_flag(result, _v6_flag(
            of.code, of.detail, tier="A", rule_id=of.rule_id or of.code,
        ))

    result.completed_checks.append("sfnt_table_inventory")
    sfnt = check_tbank_sfnt_table_inventory(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    result.stats["sfnt_table_inventory"] = sfnt.stats
    for sf in sfnt.flags:
        ingest_flag(result, _v6_flag(
            sf.code, sf.detail, tier="A", rule_id=sf.rule_id or sf.code,
        ))

    result.completed_checks.append("notdef_integrity")
    nd = check_tbank_notdef_integrity(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    result.stats["notdef_integrity"] = nd.stats
    for nf in nd.flags:
        ingest_flag(result, _v6_flag(
            nf.code, nf.detail, tier="A", rule_id=nf.rule_id or nf.code,
        ))

    result.completed_checks.append("reassembly_family_v3")
    v3 = run_tbank_reassembly_family_v3_stack(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    result.stats["reassembly_family_v3"] = v3.stats
    for note in v3.diagnostics:
        result.ignored_observations.append(note)
    for vf in v3.flags:
        ingest_flag(result, _v6_flag(
            vf.code,
            vf.detail,
            tier=vf.tier,
            rule_id=vf.rule_id or vf.code,
        ))

    result.completed_checks.append("serializer_families_v1")
    ser = check_tbank_serializer_families_v1(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    result.stats["serializer_families_v1"] = ser.stats
    if ser.evidence:
        result.stats["serializer_families_v1_evidence"] = ser.evidence
    for sf in ser.flags:
        ingest_flag(result, _v6_flag(
            sf.code,
            sf.detail,
            tier=sf.tier,
            rule_id=sf.rule_id or sf.code,
        ))

    ugi = check_tbank_used_glyph_integrity(
        pdf_bytes, producer=producer, creator=creator,
    )
    result.stats["used_glyph_integrity"] = ugi.stats
    for f in ugi.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    gst = check_glyph_slot_transplant(
        pdf_bytes, producer=producer, creator=creator,
    )
    result.stats["glyph_slot_transplant"] = gst.stats
    for f in gst.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    ga = check_tbank_glyph_atlas(pdf_bytes)
    result.stats["glyph_atlas"] = ga.stats
    for note in ga.diagnostics:
        result.ignored_observations.append(note)
    for gf in ga.flags:
        ingest_flag(result, _v6_flag(gf.code, gf.detail, tier="A", rule_id=gf.rule_id))

    reassembled = check_reassembled_bank_assets(
        pdf_bytes,
        producer=producer,
        creator=creator,
    )
    result.stats["reassembled_bank_assets"] = reassembled.stats
    for f in reassembled.flags:
        ingest_flag(result, _v6_flag(
            f.code,
            f.detail,
            tier=f.tier,
            rule_id=f.rule_id,
        ))

    result.completed_checks.append("embedded_font_reassembly_forensics")
    from ..embedded_font_reassembly import check_embedded_font_reassembly
    rebuild = check_embedded_font_reassembly(
        pdf_bytes,
        bank="tbank",
        producer=producer,
        creator=creator,
        reassembled_stats=reassembled.stats,
    )
    result.stats["embedded_font_reassembly"] = rebuild.stats
    for rf in rebuild.flags:
        ingest_flag(result, _v6_flag(
            rf.code, rf.detail, tier="A", rule_id=rf.rule_id or rf.code,
        ))

    rf = check_receipt_format(pdf_bytes, text, producer=producer, creator=creator)
    result.stats["receipt_format"] = rf.stats
    for f in rf.flags:
        ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.rule_id))

    ir = check_trailer_id_reuse(
        pdf_bytes, text, producer=producer, creator=creator, file_hash_value=file_hash,
    )
    result.stats["trailer_id_reuse"] = ir.stats
    for f in ir.flags:
        ingest_flag(result, _v6_flag(
            f.code, f.detail, tier="IGNORE", rule_id=f.rule_id,
        ))



def _stage_layout_fingerprint(pdf_bytes: bytes, text: str, result: PipelineResult) -> None:
    result.completed_checks.append("layout_fingerprint")
    if not _is_tbank_receipt(pdf_bytes, text):
        return
    lf = check_tbank_layout_fingerprint(pdf_bytes, text, shadow=False, regression_passed=True)
    result.stats["layout_fingerprint"] = lf.stats
    for ln in lf.lines[:12]:
        result.stats.setdefault("layout_lines", []).append({
            "text": ln.text,
            "end_x": round(ln.end_x, 3),
            "fitz_end_x": round(ln.fitz_end_x, 3),
            "deviation": round(ln.deviation, 3),
            "confirmed": ln.confirmed,
        })
    for d in lf.diagnostics:
        result.ignored_observations.append(d)
    for code, detail in lf.supporting_flags:
        ingest_flag(result, _v6_flag(
            code, detail, tier="B", rule_id="T-TBANK-TEXT-LAYOUT-FINGERPRINT-001",
        ))
    for code, detail in lf.hard_flags:
        ingest_flag(result, _v6_flag(
            code, detail, tier="A", rule_id="T-TBANK-TEXT-LAYOUT-FINGERPRINT-001",
        ))

    # Intra-doc value right-edge constancy (relative spread, not absolute R pin).
    edges = check_tbank_value_right_edge(pdf_bytes)
    result.stats["value_right_edge"] = edges.stats
    for f in edges.flags:
        ingest_flag(result, _v6_flag(
            f.code, f.detail, tier="A", rule_id=f.rule_id or f.code,
        ))


def _stage_metadata(
    pdf_bytes: bytes,
    result: PipelineResult,
    *,
    creation_date: str,
    producer: str = "",
    creator: str = "",
    text: str = "",
) -> None:
    result.completed_checks.append("metadata_generation")
    lex = check_info_keywords_lex(pdf_bytes, producer=producer, creator=creator)
    result.stats["info_keywords_lex"] = lex.stats
    if lex.applies and lex.mismatch:
        ingest_flag(result, _v6_flag(
            "TBANK_INFO_KEYWORDS_LEX_MISMATCH",
            lex.detail,
            tier="A",
            rule_id="K-TBANK-INFO-KEYWORDS-LEX-001",
        ))
    printed = (
        extract_receipt_datetime(text, prefer_first_line=True) if text else None
    )
    kg = check_keywords_generation(
        pdf_bytes,
        creation_date=creation_date,
        printed_datetime=printed,
    )
    result.stats["keywords_generation"] = kg.stats
    if not kg.applies:
        return
    result.stats["keywords_tail"] = kg.tail
    if kg.mismatch:
        result.stats["keywords_generation_mismatch"] = True
        ingest_flag(result, _v6_flag(
            "TBANK_KEYWORDS_GENERATION_MISMATCH",
            kg.detail,
            tier="A",
            rule_id="K-TBANK-KEYWORDS-GENERATION-001",
        ))
    elif kg.stats.get("generation") == "native_ok":
        result.ignored_observations.append(
            f"[diagnostic] /Keywords third token {kg.tail} — "
            f"штатный Jasper IB/Receipt, не влияет на verdict"
        )


def _stage_intake(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("intake")
    result.stats["size"] = len(pdf_bytes)
    if not pdf_bytes:
        result.analysis_complete = False
        return
    if len(pdf_bytes) > _MAX_BYTES:
        result.analysis_complete = False
        result.stats["budget_exceeded"] = "file_size"


def _stage_preflight(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("raw_preflight")

    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        ingest_flag(result, _v6_flag(code, detail))
    result.stats["structure"] = s1.stats

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        ingest_flag(result, _v6_flag(code, detail))

    broken, detail = xref_integrity(pdf_bytes)
    if broken and not any(f.code == "XREF_OFFSET_INVALID" for f in result.hard_flags):
        ingest_flag(result, _v6_flag("XREF_OFFSET_INVALID", detail or "нарушена xref"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams")

    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _v6_flag(code, detail))
        elif code in ("STREAM_COMPRESSION_RATIO_OUTLIER", "DECODED_STREAM_SIZE_OUTLIER",
                      "STREAM_FILTER_ANOMALY"):
            ingest_flag(result, _v6_flag(code, detail, tier="B"))
        elif code not in IGNORED_CODES:
            result.ignored_observations.append(f"[{code}] {detail}")


def _stage_active_content(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        ingest_flag(result, _v6_flag(code, detail))


def _stage_content_ast(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("content_ast")
    content = content_stream_bytes(pdf_bytes)
    if not content:
        result.ignored_observations.append("content stream не найден — stats only")
        return

    bt = len(re.findall(rb"\bBT\b", content))
    et = len(re.findall(rb"\bET\b", content))
    result.stats["bt_et"] = {"bt": bt, "et": et}
    if bt != et:
        ingest_flag(result, _v6_flag(
            "TBANK_BT_ET_MISMATCH",
            f"несбалансированные BT/ET: {bt} vs {et}",
        ))

    cs_fake, cs_detail = _content_stream_edit_trace(content)
    if cs_fake:
        ingest_flag(result, _v6_flag("TBANK_CONTENT_STREAM_EDIT", cs_detail))

    sk = content_skeleton_hash(pdf_bytes)
    result.stats["skeleton"] = sk
    if sk and sk in KNOWN_GENERATOR_SKELETONS:
        ingest_flag(result, _v6_flag(
            "TBANK_KNOWN_GENERATOR_SKELETON",
            f"известный скелет генератора фейков {sk} (0 коллизий с оригиналами)",
        ))


def _content_stream_edit_trace(content: bytes) -> tuple[bool, str]:
    pad_comments = [
        ln for ln in content.split(b"\n")
        if ln.strip().startswith(b"%") and len(ln.strip()) > 12
    ]
    if pad_comments:
        return True, (
            f"padding-комментарии (%…) в content stream "
            f"({len(pad_comments)} строк) — след ручной правки"
        )

    et_pos = content.rfind(b"ET")
    if et_pos >= 0:
        after = content[et_pos + 2:]
        pad = len(after) - len(after.lstrip(b" \t\r\n\x0c"))
        if pad > 8:
            return True, (
                f"хвостовой padding {pad} байт после ET — "
                "признак редактирования content stream"
            )

    stripped = content.rstrip(b" \t\r\n\x0c")
    tail_pad = len(content) - len(stripped)
    if stripped.endswith(b"2 J") and tail_pad > 2:
        return True, (
            f"хвостовой padding {tail_pad} байт после footer-блока — "
            "content stream пересобран не как Jasper/OpenPDF"
        )
    return False, ""


def _stage_fonts(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("fonts_cmap_glyph")

    k002 = check_k_font_002(pdf_bytes)
    if k002:
        ingest_flag(result, k002)

    k001, diag = check_k_font_001(pdf_bytes)
    if k001:
        ingest_flag(result, k001)
    for f in diag:
        if f.code == "PDF_TTF_BBOX_CROSS_LAYER_MISMATCH":
            ingest_flag(result, _v6_flag(f.code, f.detail, tier="A"))
        elif f.tier == "B":
            ingest_flag(result, f)

    forensic = run_pdf_forensics(pdf_bytes, bank="tbank", tier="full")
    result.stats["forensics"] = forensic.stats
    _FORENSICS_HARD = {
        "USED_CID_MISSING_FROM_CMAP", "CMAP_INVALID", "USED_CID_MISSING_FROM_W",
        "CMAP_W_MISMATCH", "W_ARRAY_SERIALIZATION_ANOMALY", "W_ARRAY_PRETTY_PRINTED",
        "OBJECT_GRAPH_INCONSISTENT", "MISSING_FONT_OBJECT", "MISSING_WIDTH_TABLE",
        "FONTFILE2_MISSING", "TEXT_LAYER_INCONSISTENT", "TEXT_EXTRACTION_MAPPING_ANOMALY",
        "UNICODE_MAPPING_INVALID", "GLYPH_OUTLINE_MISMATCH", "BROKEN_GLYPH_ZERO_LENGTH",
        "LOCA_TABLE_BROKEN", "GLYPH_BBOX_IMPOSSIBLE", "FONTFILE2_CID_MISSING",
    }
    # MEDIUM in forensics, but decisive for T-Bank: Jasper/OpenPDF never writes
    # Tm with ≥3 fractional digits (0 hits on чеки/т банк + Новая папка).
    _FORENSICS_TM_HARD = {
        "FIELD_POSITION_OUT_OF_PROFILE",
        "TM_NOT_RECALCULATED",
    }
    # OpenPDF genuines never keep unused CMap leftovers (0/128). SEQ phone
    # templates leave template letters like «БДМЧ» in CMap unused by text.
    _FORENSICS_OPENPDF_HARD = {
        "UNUSED_CID_PRESENT",
        "CMAP_EXTRA_SYMBOLS",
    }
    openpdf = b"OpenPDF" in (pdf_bytes or b"")
    for f in forensic.flags:
        if f.code in IGNORED_CODES:
            result.ignored_observations.append(f"[{f.code}] {f.detail}")
            continue
        if f.code in _FORENSICS_TM_HARD:
            ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.code))
            continue
        if openpdf and f.code in _FORENSICS_OPENPDF_HARD:
            ingest_flag(result, _v6_flag(f.code, f.detail, tier="A", rule_id=f.code))
            continue
        if f.code in _FORENSICS_HARD and f.weight == Weight.HIGH:
            ingest_flag(result, _v6_flag(f.code, f.detail, tier="A"))
        elif f.weight == Weight.HIGH:
            result.ignored_observations.append(f"[{f.code}] {f.detail}")
        elif f.weight == Weight.MEDIUM and f.code in SUPPORTING_GROUPS:
            ingest_flag(result, _v6_flag(f.code, f.detail, tier="B"))

    if b"ALSRubl" not in pdf_bytes and b"JSOLSA+ALSRubl" not in pdf_bytes:
        if b"/Font" in pdf_bytes and b"F3" in pdf_bytes:
            ingest_flag(result, _v6_flag(
                "F3_NOT_ALSRUBL",
                "отсутствует шрифт ALSRubl (F3) для знака рубля",
            ))


def _text_semantic_flags(text: str) -> list[V6Flag]:
    flags: list[V6Flag] = []
    if not text:
        return flags

    controls = sorted({name for ch, name in _BAD_TEXT_CONTROLS.items() if ch in text})
    if controls:
        flags.append(_v6_flag(
            "TEXT_LAYER_INCONSISTENT",
            f"в видимом тексте есть невидимые управляющие символы ({', '.join(controls)})",
        ))

    for token in re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", text):
        normalized = token.translate(_LATIN_HOMOGLYPHS)
        if token != normalized and normalized in _CORE_RU_LABELS:
            flags.append(_v6_flag(
                "BROKEN_CYRILLIC_MAPPING",
                f"служебное слово «{normalized}» набрано латинскими похожими буквами",
            ))
            break

    compact = text.replace("\u00a0", " ").replace("\u202f", " ")
    m = _COMPACT_AMOUNT_RE.search(compact)
    if m and re.search(r"(Сумма|Итого|Комиссия|Перевод)", compact, re.IGNORECASE):
        flags.append(_v6_flag(
            "FIELD_FORMAT_INVALID",
            f"денежное значение записано не банковской грамматикой: {m.group(0)}",
        ))

    rm = _RECEIPT_ID_RE.search(text)
    if rm and rm.group(2) != "":
        junk = rm.group(2)
        shown = repr(junk[:24])
        flags.append(_v6_flag(
            "TBANK_RECEIPT_ID_TRAILING_JUNK",
            f"после номера квитанции {rm.group(1)} лишний хвост {shown} — "
            f"у Jasper/OpenPDF строка обрывается на цифрах, без мусорных CID",
            rule_id="TBANK_RECEIPT_ID_TRAILING_JUNK",
        ))
    return flags


def _broken_glyphmap(text: str) -> V6Flag | None:
    if not text:
        return None
    if "\ufffd" in text:
        return _v6_flag(
            "TEXT_EXTRACTION_MAPPING_ANOMALY",
            "в текстовом слое символы замены U+FFFD — битая glyphmap",
        )
    low = text.lower()
    if "(cid:" in low:
        return _v6_flag(
            "TEXT_EXTRACTION_MAPPING_ANOMALY",
            "текст содержит необработанные CID-метки — повреждён glyphmap",
        )
    bad = sum(1 for c in text if "\u0080" <= c <= "\u009f")
    if bad >= 3:
        return _v6_flag(
            "BROKEN_CYRILLIC_MAPPING",
            f"битая кириллическая разметка ({bad} управляющих символов в тексте)",
        )
    return None


def _detect_v6_channel(text: str) -> str:
    """Подметод по v6 spec §2 — не путать карту и телефон."""
    if not text:
        return CHANNEL_PHONE
    flat = " ".join(text.split()).lower()
    if any(m in flat for m in (
        "идентификатор операции",
        "id операции в сбп",
        "id операции сбп",
        "идентификатор операции в сбп",
        "номер операции в сбп",
        "сбп id",
    )):
        return CHANNEL_SBP
    if "клиенту т-банка" in flat:
        return CHANNEL_CARD
    if any(m in flat for m in ("по номеру карты", "с карты на карту", "перевод на карту")):
        return CHANNEL_CARD
    if "на карту" in flat and ("перевод" in flat or "итого" in flat):
        return CHANNEL_CARD
    if "карта получателя" in flat and "телефон получателя" not in flat:
        return CHANNEL_CARD
    if "по номеру телефона" in flat or "телефон получателя" in flat:
        return CHANNEL_PHONE
    return detect_receipt_channel(text)


def _phone_format_flag(text: str, channel: str) -> V6Flag | None:
    if channel != CHANNEL_PHONE:
        return None
    flat = text.lower()
    if "по номеру телефона" not in flat and "телефон получателя" not in flat:
        return None
    lines = [ln.strip() for ln in text.split("\n")]
    phone = None
    for i, ln in enumerate(lines):
        if ln == "Получатель" and i > 0:
            phone = lines[i - 1]
            break
        if "телефон получателя" in ln.lower() and i + 1 < len(lines):
            phone = lines[i + 1].strip()
            break
    if not phone or _PHONE_FMT_RE.match(phone):
        return None
    return _v6_flag(
        "FIELD_FORMAT_INVALID",
        f"номер телефона «{phone[:30]}» — у Т-Банка формат «+7 (XXX) XXX-XX-XX»",
    )


def _is_tbank_receipt(pdf_bytes: bytes, text: str) -> bool:
    if _TBANK_SUBJECT in pdf_bytes:
        return True
    if not text:
        return (
            b"Receipt" in pdf_bytes
            or "Перевод".encode("utf-8") in pdf_bytes
        )
    markers = ("Перевод", "Квитанция", "Итого", "Статус")
    return sum(1 for m in markers if m in text) >= 2


_TBANK_NATIVE_TOOLING = ("openpdf", "jasperreports", "jaspersoft")
# Genuine T-Bank IB debit accounts on corpus receipts are always 40817…
_TBANK_DEBIT_ACCOUNT_PREFIXES = frozenset({"40817"})
_DEBIT_ACCOUNT_RE = re.compile(
    r"Сч[её]т\s+списания\s*[:\n\r\s]*?(408\d{2})",
    re.IGNORECASE,
)


def _tbank_native_tooling(producer: str, creator: str) -> bool:
    blob = f"{producer or ''} {creator or ''}".lower()
    return any(token in blob for token in _TBANK_NATIVE_TOOLING)


def _debit_account_prefix_flag(text: str) -> V6Flag | None:
    if not text:
        return None
    m = _DEBIT_ACCOUNT_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    prefix = m.group(1)
    if prefix in _TBANK_DEBIT_ACCOUNT_PREFIXES:
        return None
    return _v6_flag(
        "TBANK_DEBIT_ACCOUNT_PREFIX",
        (
            f"счёт списания с префиксом {prefix} — на оригиналах Т-Банка "
            f"только {'/'.join(sorted(_TBANK_DEBIT_ACCOUNT_PREFIXES))}"
        ),
        tier="A",
        rule_id="K-TBANK-DEBIT-ACCOUNT-001",
    )


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
    channel = _detect_v6_channel(text)
    subtype = detect_receipt_subtype(text) if text else detect_receipt_subtype("")
    result.channel = channel
    result.receipt_subtype = subtype
    result.stats["receipt_subtype_label"] = receipt_subtype_label(subtype)

    if not _is_tbank_receipt(pdf_bytes, text):
        result.not_a_tbank_receipt = True
        return

    # Genuine IB receipts are JasperReports + OpenPDF. Foreign tooling (PDFium,
    # Chromium, ReportLab, …) with T-Bank receipt text is decisive forgery —
    # profile-gated font/deflate HARDs never run on those producers.
    native = _tbank_native_tooling(producer, creator)
    result.stats["native_jasper_openpdf_tooling"] = native
    if not native:
        label = (producer or creator or "empty").strip() or "empty"
        ingest_flag(
            result,
            _v6_flag(
                "TBANK_FOREIGN_PRODUCER",
                f"квитанция Т-Банка собрана сторонним PDF-инструментом: «{label}» "
                "(ожидается JasperReports / OpenPDF)",
                tier="A",
                rule_id="K-TBANK-FOREIGN-PRODUCER-001",
            ),
        )
    foreign = check_foreign_producer(pdf_bytes)
    result.stats["foreign_producer"] = foreign.stats
    for sf in foreign.flags:
        ingest_flag(
            result,
            _v6_flag(sf.code, sf.detail, tier="A", rule_id="K-TBANK-FOREIGN-PRODUCER-001"),
        )

    for f in _text_semantic_flags(text):
        ingest_flag(result, f)

    debit = _debit_account_prefix_flag(text)
    if debit:
        ingest_flag(result, debit)

    bg = _broken_glyphmap(text)
    if bg:
        ingest_flag(result, bg)

    pf = _phone_format_flag(text, channel)
    if pf:
        ingest_flag(result, pf)

    competitor_hard = check_sbp_competitor_hard(pdf_bytes, text=text)
    result.stats["sbp_competitor_hard"] = competitor_hard.stats
    for code, detail in competitor_hard.flags:
        ingest_flag(result, _v6_flag(
            code,
            detail,
            tier="A",
            rule_id="K-TBANK-SBP-COMPETITOR-HARD-001",
        ))

    if channel == CHANNEL_SBP:
        from ..tbank_sbp_content import extract_sbp_opid_geometric

        opid = extract_sbp_opid_geometric(pdf_bytes, text) or extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        sbp = validate_tbank_sbp_id(
            opid or "", text, pdf_bytes,
            producer=producer, creator=creator,
        )
        result.stats["sbp_content"] = sbp.stats
        for note in sbp.diagnostics:
            result.ignored_observations.append(note)
        for sf in sbp.flags:
            ingest_flag(result, _v6_flag(
                sf.code, sf.detail,
                tier=(
                    "IGNORE"
                    if sf.code == "SBP_LINKED_TUPLE_CONFLICT"
                    else sf.tier
                ),
                rule_id=sf.rule_id,
            ))
        epoch_reuse = check_sbp_epoch_and_receipt_stem(opid or "", text)
        result.stats["sbp_epoch_reuse"] = epoch_reuse.stats
        for ef in epoch_reuse.flags:
            ingest_flag(result, _v6_flag(
                ef.code, ef.detail,
                tier=ef.tier,
                rule_id=ef.rule_id,
            ))

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes,
        bank_key="tbank",
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
            ingest_flag(result, _v6_flag(af.code, af.detail, tier="A"))
        elif af.code in ("RECEIPT_TEXT_LAYER_MISSING",):
            ingest_flag(result, _v6_flag(af.code, af.detail, tier="A"))
        elif af.code == "PDF_MODDATE_EDITED":
            ingest_flag(result, _v6_flag(af.code, af.detail, tier="B"))
        else:
            result.ignored_observations.append(f"[{af.code}] {af.detail}")

    result.stats["producer"] = producer
    result.stats["creator"] = creator
    result.stats["confirmed_jasper_profile"] = claims_confirmed_tbank_profile(
        pdf_bytes, producer=producer, creator=creator,
    )

def _stage_parity(pdf_bytes: bytes, text: str, result: PipelineResult) -> None:
    result.completed_checks.append("differential_parity")
    if not fitz:
        result.analysis_complete = False
        result.stats["fitz_missing"] = True
        return
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        t2 = doc[0].get_text() if doc.page_count else ""
        doc.close()
    except Exception:
        result.analysis_complete = False
        return

    if text and t2:
        flat_a = re.sub(r"\s+", "", text)
        flat_b = re.sub(r"\s+", "", t2)
        opid_a = extract_sbp_opid(text)
        opid_b = extract_sbp_opid(t2)
        if opid_a and opid_b and opid_a != opid_b:
            ingest_flag(result, _v6_flag(
                "TEXT_LAYER_INCONSISTENT",
                f"СБП-ID различается между parser: {opid_a} vs {opid_b}",
            ))


def run_pipeline(pdf_bytes: bytes, file_hash: str) -> PipelineResult:
    result = PipelineResult(file_hash=file_hash)

    _stage_intake(pdf_bytes, result)
    if not result.analysis_complete:
        return result

    fs = check_file_size(pdf_bytes)
    result.stats["file_size_check"] = fs.stats
    for f in fs.flags:
        ingest_flag(result, f)
    result.completed_checks.append("file_size")

    ff2s = check_fontfile2_size(pdf_bytes)
    result.stats["fontfile2_size_check"] = ff2s.stats
    for f in ff2s.flags:
        ingest_flag(result, f)
    result.completed_checks.append("fontfile2_size")

    f1shape = check_f1_subset_shape(pdf_bytes)
    result.stats["f1_subset_shape"] = f1shape.stats
    for f in f1shape.flags:
        ingest_flag(result, f)
    result.completed_checks.append("f1_subset_shape")

    f2shape = check_f2_subset_shape(pdf_bytes)
    result.stats["f2_subset_shape"] = f2shape.stats
    for f in f2shape.flags:
        ingest_flag(result, f)
    result.completed_checks.append("f2_subset_shape")

    bf_cogen = check_basefont_subset_cogen(pdf_bytes)
    result.stats["basefont_subset_cogen"] = bf_cogen.stats
    for f in bf_cogen.flags:
        ingest_flag(result, f)
    result.completed_checks.append("basefont_subset_cogen")

    # Structural reassembly residue must run before preflight early-exit:
    # atlas soft-flags used to abort the pipeline before v3 stack.
    orphan_res = check_tbank_subset_orphan_residue(pdf_bytes)
    result.stats["subset_orphan_residue"] = orphan_res.stats
    for of in orphan_res.flags:
        ingest_flag(result, _v6_flag(
            of.code, of.detail, tier=of.tier, rule_id=of.rule_id or of.code,
        ))
    result.completed_checks.append("subset_orphan_residue")

    maxp_res = check_tbank_f1_maxp_recomputed_to_subset(pdf_bytes)
    result.stats["f1_maxp_recomputed"] = maxp_res.stats
    for mf in maxp_res.flags:
        ingest_flag(result, _v6_flag(
            mf.code, mf.detail, tier=mf.tier, rule_id=mf.rule_id or mf.code,
        ))
    result.completed_checks.append("f1_maxp_recomputed")

    emit_res = check_tbank_emitter_invariants(pdf_bytes)
    result.stats["emitter_invariants"] = emit_res.stats
    for ef in emit_res.flags:
        ingest_flag(result, ef)
    result.completed_checks.append("emitter_invariants")

    spacing = check_glyph_spacing(pdf_bytes)
    result.stats["glyph_spacing"] = spacing.stats
    for f in spacing.flags:
        ingest_flag(result, f)
    result.completed_checks.append("glyph_spacing")

    cp = check_content_profile(pdf_bytes)
    result.stats["content_profile_check"] = cp.stats
    for f in cp.flags:
        ingest_flag(result, f)
    result.completed_checks.append("content_profile")

    _stage_preflight(pdf_bytes, result)
    if _has_decisive(result):
        result.stats["early_exit"] = "preflight"
        result.completed_checks.append("cross_document_intelligence")
        return result

    _stage_streams(pdf_bytes, result)
    _stage_active_content(pdf_bytes, result)
    if _has_decisive(result):
        result.stats["early_exit"] = "streams_active"
        result.completed_checks.append("cross_document_intelligence")
        return result

    _stage_content_ast(pdf_bytes, result)
    text, producer, creator, creation_date, mod_date = _pdf_text_and_metadata(pdf_bytes)
    _stage_layout_fingerprint(pdf_bytes, text, result)
    _stage_fonts(pdf_bytes, result)
    if _has_decisive(result):
        result.stats["early_exit"] = "fonts"
        result.completed_checks.append("cross_document_intelligence")
        return result

    _stage_internal_serialization(
        pdf_bytes, text, result,
        producer=producer, creator=creator, file_hash=file_hash,
    )
    if _has_decisive(result):
        # Semantics (SBP etc.) cannot overturn HARD — skip remaining CPU.
        result.stats["early_exit"] = "internal_serialization"
        result.completed_checks.append("cross_document_intelligence")
        return result

    _stage_metadata(
        pdf_bytes, result,
        creation_date=creation_date,
        producer=producer,
        creator=creator,
        text=text,
    )
    _stage_semantics(
        pdf_bytes, text, result,
        producer=producer, creator=creator,
        creation_date=creation_date, mod_date=mod_date,
        file_hash=file_hash,
    )
    if not _has_decisive(result):
        _stage_parity(pdf_bytes, text, result)

    result.completed_checks.append("cross_document_intelligence")
    return result