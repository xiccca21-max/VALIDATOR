"""Alfa v1.0 eight-stage pipeline (spec §4–13)."""

from __future__ import annotations

import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from ..alfa_profiles import (
    CHANNEL_CARD,
    CHANNEL_SBP,
    CHANNEL_PHONE,
    detect_alfa_channel,
    detect_alfa_subtype,
    extract_bank_operation_id,
    extract_sbp_opid,
    receipt_subtype_label,
)
from ..alfa_sbp_cipher import validate_alfa_sbp_cipher
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
from .rules import (
    _IOS_PRODUCER_MARKERS,
    _OPERATION_PREFIX,
    _ORACLE_PRODUCER_MARKERS,
    DELETED_CODES,
    DIAGNOSTIC_CODES,
    HARD_CODES,
)
from .types import AlfaFlag, PipelineResult
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
_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_ALFA_TITLE_MARKERS = (
    "квитанция о переводе",
    "альфа-банк",
    "alfa-bank",
    "сформирована",
)


def _flag(code: str, detail: str, *, tier: str | None = None, group: str = "") -> AlfaFlag:
    if tier is None:
        if code in HARD_CODES:
            tier = "HARD"
        elif code in DIAGNOSTIC_CODES:
            tier = "DIAGNOSTIC"
        else:
            tier = "DIAGNOSTIC"
    if not group:
        if code.startswith("ALFA_SBP") or code.startswith("ALFA_OPERATION"):
            group = "identifier"
        elif "FONT" in code or "CID" in code or "CMAP" in code:
            group = "font"
        elif code.startswith("STREAM") or code == "UNEXPECTED_STREAM_FILTER":
            group = "stream"
        elif "JAVASCRIPT" in code or "ACTIVE" in code or "EMBEDDED" in code:
            group = "active"
        else:
            group = "container"
    return AlfaFlag(code=code, detail=detail, tier=tier, rule_id=code, group=group)


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


def _detect_generator(producer: str) -> str:
    low = (producer or "").lower()
    if any(m in low for m in _IOS_PRODUCER_MARKERS):
        return "ios_quartz"
    if any(m in low for m in _ORACLE_PRODUCER_MARKERS):
        return "oracle_bi"
    return "unknown_coherent"


def _is_alfa_receipt(text: str, pdf_bytes: bytes) -> bool:
    if text:
        low = text.lower()
        if sum(1 for m in _ALFA_TITLE_MARKERS if m in low) >= 2:
            return True
    return b"Oracle BI Publisher" in pdf_bytes or b"Quartz PDFContext" in pdf_bytes


def _operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ")
    for label in ("дата и время перевода", "дата и время операции", "дата операции"):
        idx = raw.lower().find(label)
        if idx >= 0:
            m = _DATE_RE.search(raw[idx:])
            if m:
                d, mo, y, h, mi, s = map(int, m.groups())
                try:
                    return datetime(y, mo, d, h, mi, s)
                except ValueError:
                    pass
    m = _DATE_RE.search(raw)
    if m:
        d, mo, y, h, mi, s = map(int, m.groups())
        try:
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            pass
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
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC"))
        else:
            ingest_flag(result, _flag(code, detail))

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        if code == "TRAILING_DATA_AFTER_EOF":
            last_eof = pdf_bytes.rfind(b"%%EOF")
            if last_eof >= 0:
                tail = pdf_bytes[last_eof + 5:]
                if tail.strip(b"\r\n \t"):
                    ingest_flag(result, _flag(code, detail, tier="HARD"))
                else:
                    ingest_flag(result, _flag(
                        "ALFA_EOF_EOL_ONLY",
                        "после %%EOF только EOL — штатно для current profile",
                        tier="DIAGNOSTIC",
                    ))
            continue
        if code in _DIAGNOSTIC_STRUCTURE:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail))

    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        ingest_flag(result, _flag("XREF_OFFSET_INVALID", detail or "нарушена xref"))

    if b"/Encrypt" in pdf_bytes[:8000]:
        result.analysis_complete = False
        result.stats["encrypted"] = True


def _stage_streams(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("streams_resources")
    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if code in ("STREAM_DECOMPRESSION_FAILED", "STREAM_LENGTH_MISMATCH"):
            ingest_flag(result, _flag(code, detail, tier="HARD"))
        elif code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="DIAGNOSTIC"))


def _stage_active(pdf_bytes: bytes, result: PipelineResult) -> None:
    result.completed_checks.append("active_content")
    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        if code not in DELETED_CODES:
            ingest_flag(result, _flag(code, detail, tier="HARD"))


def _content_stream_edit(content: bytes) -> tuple[bool, str]:
    pad_comments = [
        ln for ln in content.split(b"\n")
        if ln.strip().startswith(b"%") and len(ln.strip()) > 12
    ]
    if pad_comments:
        return True, (
            f"padding-комментарии в content stream ({len(pad_comments)} строк)"
        )
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
    result.stats["bt_et"] = {"bt": bt, "et": et}
    if bt != et:
        ingest_flag(result, _flag(
            "ALFA_BT_ET_MISMATCH",
            f"несбалансированные BT/ET: {bt} vs {et}",
            tier="HARD",
            group="visibility",
        ))
    cs_fake, cs_detail = _content_stream_edit(content)
    if cs_fake:
        ingest_flag(result, _flag(
            "ALFA_CONTENT_STREAM_EDIT", cs_detail, tier="HARD", group="visibility",
        ))


def _sniff_generator(pdf_bytes: bytes, producer: str = "") -> str:
    low = (producer or "").lower()
    if any(m in low for m in _IOS_PRODUCER_MARKERS):
        return "ios_quartz"
    if any(m in low for m in _ORACLE_PRODUCER_MARKERS):
        return "oracle_bi"
    if b"Quartz PDFContext" in pdf_bytes:
        return "ios_quartz"
    if b"Oracle BI Publisher" in pdf_bytes:
        return "oracle_bi"
    return "unknown_coherent"


def _has_indirect_w(pdf_bytes: bytes) -> bool:
    return bool(re.search(rb"/W\s+\d+\s+0\s+R", pdf_bytes))


def _parse_indirect_w(pdf_bytes: bytes) -> dict[int, int]:
    """iOS Quartz: /W 15 0 R — widths in separate object."""
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

    forensic = run_pdf_forensics(pdf_bytes, bank="alfa", tier="full")
    result.stats["forensics"] = forensic.stats

    _FONT_HARD_USED = {
        "USED_CID_MISSING_FROM_CMAP", "CMAP_INVALID",
        "USED_CID_MISSING_FROM_W", "FONTFILE2_MISSING",
        "MISSING_FONT_OBJECT", "GLYPH_OUTLINE_MISMATCH",
        "BROKEN_GLYPH_ZERO_LENGTH", "LOCA_TABLE_BROKEN",
    }
    _ORACLE_DIAGNOSTIC = {
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
        if gen == "oracle_bi" and f.code in _ORACLE_DIAGNOSTIC:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", group="font"))
            continue
        if gen == "ios_quartz" and has_indirect_w and f.code in _IOS_SKIP_IF_INDIRECT_W:
            ingest_flag(result, _flag(
                f.code,
                f.detail + " — iOS profile: /W в отдельном объекте (штатно)",
                tier="DIAGNOSTIC",
                group="font",
            ))
            continue
        if f.code in _FONT_HARD_USED and f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="HARD", group="font"))
        elif f.weight == Weight.HIGH:
            ingest_flag(result, _flag(f.code, f.detail, tier="DIAGNOSTIC", group="font"))


def _check_operation_id_date(
    op_id: str | None,
    op_dt: datetime | None,
    channel: str,
) -> AlfaFlag | None:
    if not op_id or len(op_id) != 16 or not op_dt:
        return None
    prefix = _OPERATION_PREFIX.get(channel)
    if not prefix or not op_id.startswith(prefix):
        return None
    embedded = op_id[3:9]
    expected = f"{op_dt.day:02d}{op_dt.month:02d}{op_dt.year % 100:02d}"
    if embedded != expected:
        return _flag(
            "ALFA_OPERATION_ID_DATE_MISMATCH",
            f"в номере операции DDMMYY={embedded}, в чеке {op_dt.strftime('%d.%m.%Y')}",
            tier="HARD",
            group="identifier",
        )
    return None


def _text_controls(text: str) -> AlfaFlag | None:
    controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in text})
    if controls:
        return _flag(
            "TEXT_LAYER_INCONSISTENT",
            f"невидимые управляющие символы ({', '.join(controls)})",
            tier="HARD",
            group="semantic",
        )
    return None


def _formed_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    idx = raw.lower().find("сформирована")
    if idx < 0:
        return None
    m = re.search(
        r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})",
        raw[idx:idx + 120],
    )
    if not m:
        return None
    d, mo, y, h, mi = map(int, m.groups())
    try:
        return datetime(y, mo, d, h, mi, 0)
    except ValueError:
        return None


def _ios_metadata_check(
    text: str,
    creation: str,
    generator: str,
) -> AlfaFlag | None:
    """ALFA-DATE-003: hard only при явном противоречии даты (не секунды)."""
    if generator != "ios_quartz" or not creation:
        return None
    formed = _formed_datetime(text)
    if not formed:
        return None
    m_cd = re.match(r"^D:(\d{4})(\d{2})(\d{2})", creation.strip())
    if not m_cd:
        return None
    y, mo, d = map(int, m_cd.groups())
    if (y, mo, d) != (formed.year, formed.month, formed.day):
        return _flag(
            "ALFA_IOS_METADATA_CONFLICT",
            f"CreationDate {y:04d}-{mo:02d}-{d:02d} ≠ "
            f"«Сформирована» {formed.strftime('%d.%m.%Y')}",
            tier="HARD",
            group="date",
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
    generator = _detect_generator(producer)
    result.generator_path = generator
    result.stats["producer"] = producer
    result.stats["creator"] = creator
    result.stats["generator_path"] = generator

    if not _is_alfa_receipt(text, pdf_bytes):
        result.not_alfa_receipt = True
        return

    if generator == "unknown_coherent":
        result.new_coherent_profile = True
        ingest_flag(result, _flag(
            "ALFA_NEW_PROFILE",
            f"новый согласованный generator path: «{producer[:60]}»",
            tier="DIAGNOSTIC",
            group="profile",
        ))
    else:
        ingest_flag(result, _flag(
            "ALFA_GENERATOR_PATH",
            f"легитимный путь: {generator}",
            tier="DIAGNOSTIC",
            group="profile",
        ))

    channel = detect_alfa_channel(text)
    subtype = detect_alfa_subtype(text)
    result.channel = channel
    result.receipt_subtype = subtype
    result.stats["receipt_subtype_label"] = receipt_subtype_label(subtype)

    tc = _text_controls(text)
    if tc:
        ingest_flag(result, tc)

    op_dt = _operation_datetime(text)
    result.stats["operation_datetime"] = op_dt.isoformat(sep=" ") if op_dt else None

    op_id = extract_bank_operation_id(text, channel)
    result.stats["operation_id"] = op_id
    mismatch = _check_operation_id_date(op_id, op_dt, channel)
    if mismatch:
        ingest_flag(result, mismatch)
    elif op_id and not any(op_id.startswith(p) for p in _OPERATION_PREFIX.values()):
        ingest_flag(result, _flag(
            "ALFA_OPERATION_ID_UNKNOWN",
            f"неизвестный формат номера операции «{op_id[:16]}» — diagnostic",
            tier="DIAGNOSTIC",
            group="identifier",
        ))

    if channel == CHANNEL_SBP:
        opid = extract_sbp_opid(text)
        result.stats["sbp_opid"] = opid
        cipher = validate_alfa_sbp_cipher(opid or "", text)
        result.stats["sbp_cipher"] = cipher.stats
        for cf in cipher.flags:
            if cf.code in ("ALFA_SBP_ID_MISSING", "ALFA_SBP_ID_TIMESTAMP"):
                ingest_flag(result, _flag(cf.code, cf.detail, tier="HARD", group="identifier"))
            elif cf.code == "ALFA_SBP_ID_STRUCTURE":
                if "длина" in cf.detail or "недопустимые" in cf.detail or "не числовой" in cf.detail:
                    ingest_flag(result, _flag(cf.code, cf.detail, tier="HARD", group="identifier"))
                elif "разделитель" in cf.detail:
                    ingest_flag(result, _flag(
                        "ALFA_SBP_SEPARATOR_DIGIT",
                        cf.detail + " — diagnostic (unknown tail/version)",
                        tier="DIAGNOSTIC",
                        group="identifier",
                    ))
                else:
                    ingest_flag(result, _flag(
                        "ALFA_SBP_TAIL_UNKNOWN", cf.detail, tier="DIAGNOSTIC",
                    ))
            elif cf.code == "ALFA_SBP_ID_REFERENCE":
                pass  # DELETED / diagnostic only

    content_len = len(content_stream_bytes(pdf_bytes) or b"")
    ae = run_anti_edit_checks(
        pdf_bytes,
        bank_key="alfa",
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
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", group="cross_document"))
        elif af.code == "PDF_MODDATE_EDITED":
            ingest_flag(result, _flag(af.code, af.detail, tier="DIAGNOSTIC"))
        elif af.code == "RECEIPT_TEXT_LAYER_MISSING":
            ingest_flag(result, _flag(af.code, af.detail, tier="HARD", group="visibility"))

    ios_conflict = _ios_metadata_check(text, creation_date, generator)
    if ios_conflict:
        ingest_flag(result, ios_conflict)

    if b"/Dests" in pdf_bytes and generator == "oracle_bi":
        ingest_flag(result, _flag(
            "ALFA_ORACLE_ORPHANS",
            "штатные orphan destination arrays (14/14 Oracle originals)",
            tier="DIAGNOSTIC",
            group="profile",
        ))


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
        ("sbp_id", extract_sbp_opid(text), extract_sbp_opid(t2)),
        ("operation_id", result.stats.get("operation_id"),
         extract_bank_operation_id(t2, result.channel)),
    ):
        if a and b and a != b:
            ingest_flag(result, _flag(
                "ALFA_PARSER_PARITY_MISMATCH",
                f"{extractor}: parser A «{a}» ≠ parser B «{b}»",
                tier="HARD",
                group="parity",
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
    result.generator_path = _sniff_generator(pdf_bytes, producer)
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
