"""A-TBANK-F2-NOTDEF-GLYPH-INTEGRITY-001 — F2 .notdef (GID 0) HARD.

Native Jasper/OpenPDF T-Bank SBP embeds a nonempty .notdef in F2 (loca slice
length 58 for the current TinkoffSans-Medium fingerprint). Reassemblers that
strip GID 0 from F2 while leaving F1/F3 intact → immediate ФЕЙК.

No shadow mode. Independent of used-CID / Tj presence.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

from .corpus_profiles import CHANNEL_SBP, detect_receipt_channel
from .structure import content_stream_bytes
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_reassembly_family_v3 import (
    _cids_from_operand,
    extract_used_cids,
    resolve_font_graph,
)

RULE_EMPTY = "A-TBANK-F2-NOTDEF-GLYPH-INTEGRITY-001"
RULE_NATIVE = "A-TBANK-F2-NOTDEF-NATIVE-PROFILE-001"
RULE_ASYMM = "A-TBANK-FONT-NOTDEF-ASYMMETRY-001"
RULE_AMOUNT = "A-TBANK-AMOUNT-TEXT-SERIALIZATION-001"
RULE_USED_CID = "A-TBANK-USED-CID-MISSING-FROM-CMAP-001"

CODE_EMPTY = "TBANK_F2_NOTDEF_GLYPH_EMPTY"
CODE_NATIVE = "TBANK_F2_NOTDEF_NATIVE_PROFILE_MISMATCH"
CODE_ASYMM = "TBANK_FONT_NOTDEF_ASYMMETRY"
CODE_AMOUNT = "TBANK_AMOUNT_TEXT_SERIALIZATION_MISMATCH"
CODE_USED_CID = "USED_CID_MISSING_FROM_CMAP"

EXPECTED_F2_NOTDEF_LENGTH = 58

# Fingerprint of the current native TinkoffSans-Medium F2 subset.
_NATIVE_F2_FINGERPRINT = {
    "units_per_em": 1000,
    "num_glyphs": 479,
    "number_of_h_metrics": 479,
    "bbox": (-37, -203, 1033, 879),
    "created": 3723266036,
    "modified": 3724914673,
}

_SUBJECT_MARKERS = (b"/reports/IB/Receipt", b"IB/Receipt")
_AMOUNT_AFTER_ITOGO_RE = re.compile(
    r"Итого\s*([^\n]{0,48})",
    re.UNICODE,
)


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_EMPTY
    tier: str = "A"
    group: str = "font_cmap_glyph"


@dataclass
class NotdefIntegrityResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class SfntFont:
    tables: dict[bytes, bytes]
    num_glyphs: int
    index_to_loc_format: int
    units_per_em: int
    bbox: tuple[int, int, int, int]
    created: int
    modified: int
    number_of_h_metrics: int
    loca_offsets: list[int]


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


def profile_gate_notdef(
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
    producer_ok = "OpenPDF 1.3.30.jaspersoft.2" in (producer or "") or (
        "openpdf 1.3.30" in (producer or "").lower()
        and "jaspersoft" in (producer or "").lower()
    )
    creator_ok = "JasperReports Library version 6.20.3" in (creator or "") or (
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


def parse_sfnt(ttf: bytes) -> SfntFont | None:
    """Parse SFNT/TrueType after /Filter decode. Returns None if tables missing."""
    if not ttf or len(ttf) < 12:
        return None
    try:
        num_tables = struct.unpack(">H", ttf[4:6])[0]
    except struct.error:
        return None
    need = 12 + num_tables * 16
    if len(ttf) < need or num_tables < 1 or num_tables > 64:
        return None

    tables: dict[bytes, bytes] = {}
    for i in range(num_tables):
        o = 12 + i * 16
        tag, _checksum, offset, length = struct.unpack(">4sIII", ttf[o:o + 16])
        if offset + length > len(ttf):
            return None
        tables[tag] = ttf[offset:offset + length]

    for req in (b"maxp", b"loca", b"glyf", b"head"):
        if req not in tables:
            return None

    head = tables[b"head"]
    maxp = tables[b"maxp"]
    if len(head) < 54 or len(maxp) < 6:
        return None

    units_per_em = struct.unpack(">H", head[18:20])[0]
    created = struct.unpack(">Q", head[20:28])[0]
    modified = struct.unpack(">Q", head[28:36])[0]
    x_min, y_min, x_max, y_max = struct.unpack(">hhhh", head[36:44])
    index_to_loc_format = struct.unpack(">H", head[50:52])[0]
    num_glyphs = struct.unpack(">H", maxp[4:6])[0]

    number_of_h_metrics = 0
    if b"hhea" in tables and len(tables[b"hhea"]) >= 36:
        number_of_h_metrics = struct.unpack(">H", tables[b"hhea"][34:36])[0]

    loca_blob = tables[b"loca"]
    offsets: list[int] = []
    if index_to_loc_format == 0:
        # short: uint16_be * 2
        if len(loca_blob) < (num_glyphs + 1) * 2:
            return None
        for i in range(num_glyphs + 1):
            offsets.append(struct.unpack(">H", loca_blob[i * 2:i * 2 + 2])[0] * 2)
    else:
        if len(loca_blob) < (num_glyphs + 1) * 4:
            return None
        for i in range(num_glyphs + 1):
            offsets.append(struct.unpack(">I", loca_blob[i * 4:i * 4 + 4])[0])

    return SfntFont(
        tables=tables,
        num_glyphs=num_glyphs,
        index_to_loc_format=index_to_loc_format,
        units_per_em=units_per_em,
        bbox=(x_min, y_min, x_max, y_max),
        created=created,
        modified=modified,
        number_of_h_metrics=number_of_h_metrics,
        loca_offsets=offsets,
    )


def get_glyph_length(font: SfntFont, gid: int) -> int | None:
    if gid < 0 or gid + 1 >= len(font.loca_offsets):
        return None
    return int(font.loca_offsets[gid + 1]) - int(font.loca_offsets[gid])


def is_native_f2_tinkoffsans_medium(font: SfntFont) -> bool:
    fp = _NATIVE_F2_FINGERPRINT
    return (
        font.units_per_em == fp["units_per_em"]
        and font.num_glyphs == fp["num_glyphs"]
        and font.number_of_h_metrics == fp["number_of_h_metrics"]
        and font.bbox == fp["bbox"]
        and font.created == fp["created"]
        and font.modified == fp["modified"]
    )


def normalize_amount(text: str) -> str:
    """Digit-only amount key: '34985i' ≡ '34 985 i' ≡ '34\\x03985\\x03₽'."""
    return re.sub(r"\D+", "", text or "")


def _f2_amount_operand_after_itogo(pdf: bytes) -> tuple[str, list[int], str]:
    """Return (mapped_chars, cids, raw_visual) for the F2 amount after «Итого»."""
    cs = content_stream_bytes(pdf) or b""
    graphs = resolve_font_graph(pdf)
    tu = (graphs.get("F2").tounicode if graphs.get("F2") else {}) or {}
    cur = ""
    seen_itogo = False
    for m in re.finditer(
        rb"/F([123])\s+[\d.]+\s+Tf"
        rb"|(\((?:\\.|[^\\)])*\))\s*T[Jj]"
        rb"|(<([0-9A-Fa-f]+)>)\s*T[Jj]",
        cs,
    ):
        if m.group(1):
            cur = m.group(1).decode("ascii")
            continue
        if cur != "2":
            continue
        if m.group(2):
            tok = m.group(2)
            cids = _cids_from_operand(tok)
        else:
            hexs = (m.group(4) or b"").decode("ascii")
            cids = [int(hexs[i:i + 4], 16) for i in range(0, len(hexs), 4) if hexs[i:i + 4]]
        chars = "".join(tu.get(c, "") for c in cids)
        if chars.replace(" ", "") == "Итого":
            seen_itogo = True
            continue
        if not seen_itogo:
            continue
        has_digit = any((tu.get(c) or "").isdigit() for c in cids) or any(
            c >= 300 for c in cids
        )
        if not has_digit and 3 not in cids:
            continue
        mapped = "".join(tu.get(c, "") for c in cids)
        # Visual with unmapped CIDs as empty → compact form like 34985
        visual = "".join(tu.get(c, "") if c in tu else "" for c in cids)
        return mapped, cids, visual
    return "", [], ""


def check_amount_text_serialization(pdf: bytes, text: str = "") -> list[HardFlag]:
    """HARD when top «Итого» amount lacks canonical thousand separators in text layer.

    File-local anomaly (e.g. sbp30_18) — not a series blacklist.
    """
    if not text:
        text = _pdf_text(pdf)
    m = _AMOUNT_AFTER_ITOGO_RE.search(text or "")
    extracted = (m.group(1) if m else "").strip()
    if m and (not extracted or not any(ch.isdigit() for ch in extracted)):
        tail = (text or "")[m.end():]
        for line in tail.splitlines():
            if line.strip():
                extracted = line.strip()
                break

    graphs = resolve_font_graph(pdf)
    g2 = graphs.get("F2")
    tu = (g2.tounicode if g2 else {}) or {}

    mapped, cids, _visual = _f2_amount_operand_after_itogo(pdf)
    probe = extracted or mapped
    digits = normalize_amount(probe)
    if len(digits) < 4:
        return []

    has_ws_sep = bool(re.search(r"\d[\s\u00a0\u202f]\d", probe))
    sep_cid_used = 3 in cids
    sep_char = tu.get(3) or ""
    sep_mapped_ws = bool(sep_char) and sep_char.isspace()
    mapped_ws = bool(re.search(r"\d\s+\d", mapped)) if mapped else False

    # Equivalence: compact digits match spaced form (value-preserving).
    compact = digits
    parts: list[str] = []
    rest = compact
    while len(rest) > 3:
        parts.append(rest[-3:])
        rest = rest[:-3]
    if rest:
        parts.append(rest)
    spaced = " ".join(reversed(parts)) + " i"
    if normalize_amount(compact) != normalize_amount(spaced):
        return []

    if has_ws_sep or mapped_ws or (sep_cid_used and sep_mapped_ws):
        return []

    # Collapsed Итого amount (no whitespace separators in text / unmapped sep CID).
    return [HardFlag(
        code=CODE_AMOUNT,
        detail=(
            f"верхний блок «Итого» без канонических разделителей тысяч "
            f"(extracted={probe!r} digits={digits})"
        ),
        rule_id=RULE_AMOUNT,
    )]


def check_used_cid_missing_from_cmap(pdf: bytes) -> list[HardFlag]:
    """HARD: used F2 CIDs from Tj/TJ must all appear in ToUnicode (Identity-H)."""
    graphs = resolve_font_graph(pdf)
    g2 = graphs.get("F2")
    if not g2:
        return []
    used = extract_used_cids(pdf).get("F2", set())
    mapped = set(g2.tounicode or {})
    missing = sorted(used - mapped)
    if not missing:
        return []
    return [HardFlag(
        code=CODE_USED_CID,
        detail=(
            f"F2: used CID отсутствуют в ToUnicode: {missing[:12]}"
            + (f" (+{len(missing) - 12})" if len(missing) > 12 else "")
        ),
        rule_id=RULE_USED_CID,
    )]


def check_tbank_notdef_integrity(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> NotdefIntegrityResult:
    out = NotdefIntegrityResult()
    gate_ok, gate_stats = profile_gate_notdef(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = resolve_font_graph(pdf_bytes)
    out.stats["font_roles"] = sorted(graphs)
    lengths: dict[str, int | None] = {}

    for role in ("F1", "F2", "F3"):
        g = graphs.get(role)
        ttf = g.fontfile2_decoded if g else b""
        if not ttf:
            lengths[role] = None
            continue
        font = parse_sfnt(ttf)
        if font is None:
            lengths[role] = None
            out.stats[f"{role}_sfnt"] = "parse_failed"
            continue
        glen = get_glyph_length(font, 0)
        lengths[role] = glen
        out.stats[f"{role}_gid0"] = {
            "glyph_length": glen,
            "loca_0": font.loca_offsets[0] if font.loca_offsets else None,
            "loca_1": font.loca_offsets[1] if len(font.loca_offsets) > 1 else None,
            "num_glyphs": font.num_glyphs,
            "index_to_loc_format": font.index_to_loc_format,
            "units_per_em": font.units_per_em,
            "bbox": font.bbox,
            "created": font.created,
            "modified": font.modified,
            "number_of_h_metrics": font.number_of_h_metrics,
            "native_f2_fingerprint": (
                is_native_f2_tinkoffsans_medium(font) if role == "F2" else None
            ),
        }

        if role != "F2" or font is None or glen is None:
            continue

        gid0_start = font.loca_offsets[0]
        gid0_end = font.loca_offsets[1]
        if glen <= 0:
            out.flags.append(HardFlag(
                code=CODE_EMPTY,
                detail=(
                    f"F2 GID 0 (.notdef) empty: loca[0]={gid0_start} "
                    f"loca[1]={gid0_end} glyph_length={glen} "
                    f"numGlyphs={font.num_glyphs} "
                    f"indexToLocFormat={font.index_to_loc_format}"
                ),
                rule_id=RULE_EMPTY,
            ))

        if is_native_f2_tinkoffsans_medium(font) and glen != EXPECTED_F2_NOTDEF_LENGTH:
            out.flags.append(HardFlag(
                code=CODE_NATIVE,
                detail=(
                    f"F2 native TinkoffSans-Medium .notdef length mismatch: "
                    f"expected={EXPECTED_F2_NOTDEF_LENGTH} actual={glen}"
                ),
                rule_id=RULE_NATIVE,
            ))

    f1_len = lengths.get("F1")
    f2_len = lengths.get("F2")
    f3_len = lengths.get("F3")
    out.stats["gid0_lengths"] = lengths
    if (
        f1_len is not None
        and f2_len is not None
        and f3_len is not None
        and f1_len > 0
        and f2_len == 0
        and f3_len > 0
    ):
        out.flags.append(HardFlag(
            code=CODE_ASYMM,
            detail=(
                f"notdef asymmetry: F1={f1_len} F2={f2_len} F3={f3_len} "
                f"— .notdef stripped only from F2"
            ),
            rule_id=RULE_ASYMM,
        ))

    # Independent of notdef: used CID ↔ ToUnicode + Итого amount serialization.
    out.flags.extend(check_used_cid_missing_from_cmap(pdf_bytes))
    out.flags.extend(check_amount_text_serialization(pdf_bytes, text=text or _pdf_text(pdf_bytes)))

    # Deduplicate identical codes (keep first detail).
    seen: set[str] = set()
    uniq: list[HardFlag] = []
    for f in out.flags:
        if f.code in seen:
            continue
        seen.add(f.code)
        uniq.append(f)
    out.flags = uniq
    return out
