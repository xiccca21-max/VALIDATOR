"""A-TBANK-TTF-SFNT-TABLE-INVENTORY-001 — F1 FontFile2 SFNT table inventory HARD.

Native Jasper/OpenPDF T-Bank SBP F1 subset uses an exact 9-table inventory.
Any extra tag (including inert padding ``ZZZZ``) or missing required tag → ФЕЙК.

No shadow mode. Payload SHA is telemetry only — never a blacklist key.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass, field
from typing import Any

from .corpus_profiles import CHANNEL_SBP, detect_receipt_channel
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_reassembly_family_v3 import resolve_font_graph

RULE_INVENTORY = "A-TBANK-TTF-SFNT-TABLE-INVENTORY-001"
RULE_ZZZZ = "A-TBANK-TTF-INERT-PADDING-TABLE-001"

CODE_UNEXPECTED = "TBANK_TTF_UNEXPECTED_SFNT_TABLE"
CODE_MISSING = "TBANK_TTF_REQUIRED_SFNT_TABLE_MISSING"
CODE_ZZZZ = "TBANK_TTF_INERT_PADDING_TABLE"

EXPECTED_F1_TABLES: frozenset[bytes] = frozenset({
    b"cvt ",
    b"fpgm",
    b"glyf",
    b"head",
    b"hhea",
    b"hmtx",
    b"loca",
    b"maxp",
    b"prep",
})

_SUBJECT_MARKERS = (b"/reports/IB/Receipt", b"IB/Receipt")


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_INVENTORY
    tier: str = "A"
    group: str = "font_cmap_glyph"


@dataclass
class SfntInventoryResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return round(ent, 6)


def _pdf_text(pdf: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text or ""
    except Exception:
        return ""


def _meta(pdf: bytes) -> tuple[str, str]:
    try:
        import fitz
        doc = fitz.open(stream=pdf, filetype="pdf")
        meta = doc.metadata or {}
        doc.close()
        return str(meta.get("producer") or ""), str(meta.get("creator") or "")
    except Exception:
        return "", ""


def _is_tbank_receipt(pdf: bytes, text: str) -> bool:
    if any(m in pdf for m in _SUBJECT_MARKERS):
        return True
    if not text:
        return b"Receipt" in pdf or "Перевод".encode("utf-8") in pdf
    markers = ("Перевод", "Квитанция", "Итого", "Статус")
    return sum(1 for m in markers if m in text) >= 2


def profile_gate_sfnt(
    pdf: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> tuple[bool, dict[str, Any]]:
    if not producer and not creator:
        producer, creator = _meta(pdf)
    if not text:
        text = _pdf_text(pdf)
    channel = detect_receipt_channel(text)
    flat = " ".join(text.split()).lower()
    if any(m in flat for m in (
        "идентификатор операции",
        "id операции в сбп",
        "id операции сбп",
        "номер операции в сбп",
        "сбп id",
        "системы быстрых платежей",
    )):
        channel = CHANNEL_SBP
    confirmed = claims_confirmed_tbank_profile(
        pdf, producer=producer, creator=creator,
    )
    subject_ok = any(m in pdf for m in _SUBJECT_MARKERS)
    producer_ok = "openpdf 1.3.30" in (producer or "").lower()
    creator_ok = (
        "jasperreports" in (creator or "").lower()
        and "6.20.3" in (creator or "")
    )
    receipt_ok = _is_tbank_receipt(pdf, text)
    ok = bool(
        receipt_ok
        and channel == CHANNEL_SBP
        and subject_ok
        and producer_ok
        and creator_ok
        and confirmed
    )
    return ok, {
        "profile_gate": ok,
        "channel": channel,
        "subject_ok": subject_ok,
        "producer_ok": producer_ok,
        "creator_ok": creator_ok,
        "confirmed": confirmed,
        "receipt_ok": receipt_ok,
        "profile_id": PROFILE_ID,
        "producer": producer,
        "creator": creator,
    }


@dataclass
class SfntRecord:
    tag: bytes
    checksum: int
    offset: int
    length: int


def parse_sfnt_directory(ttf: bytes) -> tuple[dict[str, Any], list[SfntRecord], list[str]]:
    """Parse SFNT directory. Returns (header_stats, records, structural_errors)."""
    errors: list[str] = []
    if len(ttf) < 12:
        return {}, [], ["fontfile2 too short for SFNT header"]

    sfnt_version = ttf[0:4]
    num_tables, search_range, entry_selector, range_shift = struct.unpack(
        ">HHHH", ttf[4:12]
    )
    header = {
        "sfnt_version": sfnt_version.hex(),
        "num_tables": num_tables,
        "search_range": search_range,
        "entry_selector": entry_selector,
        "range_shift": range_shift,
    }
    need = 12 + num_tables * 16
    if len(ttf) < need:
        errors.append(f"directory truncated: need {need}, have {len(ttf)}")
        return header, [], errors

    records: list[SfntRecord] = []
    for i in range(num_tables):
        o = 12 + i * 16
        tag, checksum, offset, length = struct.unpack(">4sIII", ttf[o:o + 16])
        records.append(SfntRecord(tag=tag, checksum=checksum, offset=offset, length=length))

    if num_tables != len(records):
        errors.append(f"num_tables {num_tables} != len(records) {len(records)}")

    if num_tables > 0:
        # searchRange == 16 * 2**floor(log2(num_tables))
        flo = int(math.floor(math.log2(num_tables)))
        expected_search = 16 * (2 ** flo)
        expected_entry = flo
        expected_shift = num_tables * 16 - expected_search
        if search_range != expected_search:
            errors.append(
                f"searchRange {search_range} ≠ {expected_search}"
            )
        if entry_selector != expected_entry:
            errors.append(
                f"entrySelector {entry_selector} ≠ {expected_entry}"
            )
        if range_shift != expected_shift:
            errors.append(
                f"rangeShift {range_shift} ≠ {expected_shift}"
            )

    # Offset / overlap checks
    ranges: list[tuple[int, int, bytes]] = []
    for rec in records:
        if rec.offset % 4 != 0:
            errors.append(
                f"tag {rec.tag.decode('latin1', 'replace')!r} "
                f"offset {rec.offset} not 4-aligned"
            )
        end = rec.offset + rec.length
        if end > len(ttf):
            errors.append(
                f"tag {rec.tag.decode('latin1', 'replace')!r} "
                f"extends past EOF ({end} > {len(ttf)})"
            )
            continue
        ranges.append((rec.offset, end, rec.tag))
    ranges.sort()
    for i in range(len(ranges) - 1):
        _a0, a1, ta = ranges[i]
        b0, _b1, tb = ranges[i + 1]
        if b0 < a1:
            errors.append(
                f"tables overlap: {ta.decode('latin1', 'replace')!r} "
                f"and {tb.decode('latin1', 'replace')!r}"
            )

    return header, records, errors


def _calc_table_checksum(payload: bytes) -> int:
    """TrueType table checksum (sum of BE uint32, zero-padded to 4)."""
    if len(payload) % 4:
        payload = payload + b"\x00" * (4 - len(payload) % 4)
    total = 0
    for i in range(0, len(payload), 4):
        total = (total + struct.unpack(">I", payload[i:i + 4])[0]) & 0xFFFFFFFF
    return total


def check_tbank_sfnt_table_inventory(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> SfntInventoryResult:
    out = SfntInventoryResult()
    gate_ok, gate_stats = profile_gate_sfnt(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = resolve_font_graph(pdf_bytes)
    f1 = graphs.get("F1")
    if not f1 or not f1.fontfile2_decoded:
        out.stats["skipped"] = "f1_fontfile2_missing"
        return out

    ttf = f1.fontfile2_decoded
    header, records, struct_errors = parse_sfnt_directory(ttf)
    out.stats["sfnt_header"] = header
    out.stats["f1_fontfile2_num"] = f1.fontfile2_num
    out.stats["f1_type0_num"] = f1.type0_num

    if struct_errors:
        out.stats["sfnt_directory_errors"] = struct_errors
        out.flags.append(HardFlag(
            code=CODE_UNEXPECTED,
            detail=(
                "F1 FontFile2 SFNT directory invalid: "
                + "; ".join(struct_errors[:6])
            ),
            rule_id=RULE_INVENTORY,
        ))

    actual_tags = {rec.tag for rec in records}
    out.stats["f1_sfnt_tags"] = sorted(
        t.decode("latin1", "replace") for t in actual_tags
    )
    out.stats["f1_num_tables"] = len(records)

    unexpected = actual_tags - EXPECTED_F1_TABLES
    missing = EXPECTED_F1_TABLES - actual_tags

    # Telemetry for unknown tables (SHA never drives verdict)
    unknown_telemetry: list[dict[str, Any]] = []
    for rec in records:
        if rec.tag in EXPECTED_F1_TABLES:
            continue
        payload = b""
        if rec.offset + rec.length <= len(ttf):
            payload = ttf[rec.offset:rec.offset + rec.length]
        calc = _calc_table_checksum(payload) if payload else None
        # head checksumAdjustment complicates head; for unknown tags use raw sum
        unknown_telemetry.append({
            "tag": rec.tag.decode("latin1", "replace"),
            "offset": rec.offset,
            "length": rec.length,
            "checksum_dir": rec.checksum,
            "checksum_calc": calc,
            "entropy": _shannon_entropy(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        })
    if unknown_telemetry:
        out.stats["unknown_table_telemetry"] = unknown_telemetry

    if unexpected:
        out.flags.append(HardFlag(
            code=CODE_UNEXPECTED,
            detail=(
                f"F1 unexpected SFNT tables "
                f"{sorted(t.decode('latin1', 'replace') for t in unexpected)} "
                f"(num_tables={len(records)}; "
                f"expected exact set "
                f"{sorted(t.decode('latin1', 'replace') for t in EXPECTED_F1_TABLES)})"
            ),
            rule_id=RULE_INVENTORY,
        ))
        out.stats["unexpected_tags"] = sorted(
            t.decode("latin1", "replace") for t in unexpected
        )

    if missing:
        out.flags.append(HardFlag(
            code=CODE_MISSING,
            detail=(
                f"F1 missing required SFNT tables "
                f"{sorted(t.decode('latin1', 'replace') for t in missing)}"
            ),
            rule_id=RULE_INVENTORY,
        ))
        out.stats["missing_tags"] = sorted(
            t.decode("latin1", "replace") for t in missing
        )

    # Exact malicious inert-padding signature
    for rec in records:
        if rec.tag != b"ZZZZ":
            continue
        payload = b""
        if rec.offset + rec.length <= len(ttf):
            payload = ttf[rec.offset:rec.offset + rec.length]
        ent = _shannon_entropy(payload)
        out.flags.append(HardFlag(
            code=CODE_ZZZZ,
            detail=(
                f"F1 inert padding SFNT table ZZZZ "
                f"length={rec.length} entropy={ent}"
            ),
            rule_id=RULE_ZZZZ,
        ))
        out.stats["zzzz"] = {
            "length": rec.length,
            "entropy": ent,
            "offset": rec.offset,
            # telemetry only
            "payload_sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        }
        break

    out.stats["inventory_canonical"] = (
        actual_tags == EXPECTED_F1_TABLES and not struct_errors
    )
    return out
