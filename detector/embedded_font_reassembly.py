"""Embedded FontFile2 reassembly forensics (cross-bank HARD stage).

Stage name: embedded_font_reassembly_forensics

Runs after FontFile2 decompression / font extraction and before final verdict.
All checks use programmatic TrueType table contents (head/maxp/hhea/hmtx/loca/
glyf/cmap/fpgm/prep/cvt), never file SHA alone as decisive evidence.

Novelty of FontFile2 SHA / subset prefix / new glyph is NEVER solo-HARD.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field
from typing import Any

from .ff2_pool import _extract_fontfile2
from .pdf_forensics import _extract_font_programs, _ttf_tables
from .structure import content_skeleton_hash, content_stream_bytes

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

from io import BytesIO

# --- Canonical source-font epochs (Mac epoch seconds in head table) ---
ALFA_HEAD_CREATED = 2931866140
ALFA_HEAD_MODIFIED = 3170332026

SBER_HEAD_CREATED = 2732795690
SBER_HEAD_MODIFIED = 3480576291
SBER_FULL_NUMGLYPHS = 3419
SBER_FONT_STRUCT_FP = "6e5a8c5f41e579a8"  # fpgm|prep|cvt|head(ts)|maxp over 22 originals

TBANK_F1_CREATED, TBANK_F1_MODIFIED = 3717379206, 3722743619
TBANK_F2_CREATED, TBANK_F2_MODIFIED = 3723266036, 3724914673
TBANK_F3_CREATED, TBANK_F3_MODIFIED = 3271726178, 3271728753
TBANK_F3_GLYF_SHA12 = "a168925c61e9"

_REQUIRED_TAGS = (
    b"head", b"maxp", b"hhea", b"hmtx", b"loca", b"glyf",
    b"cmap", b"fpgm", b"prep", b"cvt ",
)

_TJ_RE = re.compile(rb"(\((?:\\.|[^\\)])*\)|<([0-9A-Fa-f]+)>)(?:\s*Tj|\s*TJ)")
_HEX_TJ_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*Tj")
_PAREN_TJ_RE = re.compile(rb"(\((?:\\.|[^\\)])*\))\s*Tj")


@dataclass
class RebuildFlag:
    code: str
    detail: str
    tier: str = "HARD"
    group: str = "embedded_font_reassembly"
    rule_id: str = ""


@dataclass
class RebuildResult:
    flags: list[RebuildFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, rule_id: str = "") -> RebuildFlag:
    return RebuildFlag(
        code=code,
        detail=detail,
        tier="HARD",
        group="embedded_font_reassembly",
        rule_id=rule_id or code,
    )


def _sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def parse_ttf_tables(ttf: bytes) -> dict[str, bytes]:
    """Return tag→raw table bytes (latin1 tag keys)."""
    out: dict[str, bytes] = {}
    for tag, (off, ln) in _ttf_tables(ttf).items():
        key = tag.decode("latin1", "replace")
        out[key] = ttf[off:off + ln]
    return out


def head_timestamps(ttf: bytes) -> tuple[int | None, int | None]:
    tables = parse_ttf_tables(ttf)
    head = tables.get("head") or b""
    if len(head) < 36:
        return None, None
    return (
        struct.unpack(">Q", head[20:28])[0],
        struct.unpack(">Q", head[28:36])[0],
    )


def maxp_num_glyphs(ttf: bytes) -> int | None:
    tables = parse_ttf_tables(ttf)
    maxp = tables.get("maxp") or b""
    if len(maxp) < 6:
        return None
    return struct.unpack(">H", maxp[4:6])[0]


def structural_fingerprint(ttf: bytes) -> dict[str, Any]:
    """Content-stable structural fingerprint from required TTF tables."""
    tables = parse_ttf_tables(ttf)
    created, modified = head_timestamps(ttf)
    ng = maxp_num_glyphs(ttf)
    tag_hashes = {
        tag: _sha16(tables[tag])
        for tag in ("fpgm", "prep", "cvt ", "cmap", "hhea")
        if tag in tables
    }
    # head with checksumAdjustment zeroed but timestamps kept
    head = bytearray(tables.get("head") or b"")
    if len(head) >= 12:
        head[8:12] = b"\x00\x00\x00\x00"
    head_fp = _sha16(bytes(head)) if head else ""
    glyf = tables.get("glyf") or b""
    loca = tables.get("loca") or b""
    parts = []
    for tag in ("fpgm", "prep", "cvt ", "head", "maxp"):
        raw = tables.get(tag)
        if not raw:
            continue
        if tag == "head":
            raw = bytes(head) if head else raw
        parts.append(tag.encode("latin1") + raw)
    struct_fp = _sha16(b"".join(parts)) if parts else ""
    return {
        "created": created,
        "modified": modified,
        "numGlyphs": ng,
        "table_tags": sorted(tables),
        "tag_hashes": tag_hashes,
        "head_fp": head_fp,
        "glyf_sha12": _sha12(glyf) if glyf else "",
        "loca_sha12": _sha12(loca) if loca else "",
        "struct_fp": struct_fp,
        "size": len(ttf),
    }


def loca_glyf_consistent(ttf: bytes) -> tuple[bool, str]:
    tables = parse_ttf_tables(ttf)
    head = tables.get("head") or b""
    loca = tables.get("loca") or b""
    glyf = tables.get("glyf") or b""
    ng = maxp_num_glyphs(ttf)
    if not head or not loca or not glyf or ng is None:
        return False, "missing head/loca/glyf/maxp"
    index_fmt = struct.unpack(">H", head[50:52])[0] if len(head) >= 52 else 0
    try:
        if index_fmt == 0:
            if len(loca) < 2 * (ng + 1):
                return False, f"short loca len={len(loca)} for numGlyphs={ng}"
            offs = [
                struct.unpack(">H", loca[i:i + 2])[0] * 2
                for i in range(0, 2 * (ng + 1), 2)
            ]
        else:
            if len(loca) < 4 * (ng + 1):
                return False, f"long loca len={len(loca)} for numGlyphs={ng}"
            offs = [
                struct.unpack(">I", loca[i:i + 4])[0]
                for i in range(0, 4 * (ng + 1), 4)
            ]
    except struct.error:
        return False, "loca unpack failed"
    if any(offs[i] > offs[i + 1] for i in range(len(offs) - 1)):
        return False, "loca offsets not monotonic"
    if offs[-1] > len(glyf):
        return False, f"loca end {offs[-1]} > glyf len {len(glyf)}"
    return True, "ok"


def nonempty_glyph_count(ttf: bytes) -> int:
    if TTFont is None:
        return -1
    try:
        tt = TTFont(BytesIO(ttf))
        glyf = tt["glyf"]
        return sum(
            1
            for name in tt.getGlyphOrder()
            if int(getattr(glyf[name], "numberOfContours", 0) or 0) != 0
        )
    except Exception:
        return -1


def _producer_creator(pdf_bytes: bytes) -> tuple[str, str]:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = dict(doc.metadata or {})
        doc.close()
        return str(meta.get("producer") or ""), str(meta.get("creator") or "")
    except Exception:
        pass
    prod_m = re.search(rb"/Producer\s*\(((?:\\.|[^\\)])*)\)", pdf_bytes)
    cre_m = re.search(rb"/Creator\s*\(((?:\\.|[^\\)])*)\)", pdf_bytes)

    def _dec(m: re.Match[bytes] | None) -> str:
        if not m:
            return ""
        return m.group(1).decode("latin1", "replace")

    return _dec(prod_m), _dec(cre_m)


def is_alfa_oracle_or_quartz(producer: str, creator: str) -> bool:
    blob = f"{producer}\n{creator}".lower()
    return (
        "oracle bi" in blob
        or "quartz pdfcontext" in blob
        or "pdfcontext" in blob
    )


def is_sber_jasper(producer: str, creator: str) -> bool:
    blob = f"{producer}\n{creator}".lower()
    return "itext" in blob or "jasper" in blob


def is_tbank_jasper_openpdf(producer: str, creator: str) -> bool:
    blob = f"{producer}\n{creator}".lower()
    return "openpdf" in blob and "jasper" in blob


def _decode_pdf_string(tok: bytes) -> bytes:
    assert tok.startswith(b"(") and tok.endswith(b")")
    s = tok[1:-1]
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i:i + 1] == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt in b"nrtbf()\\":
                out.extend({
                    b"n": b"\n", b"r": b"\r", b"t": b"\t",
                    b"b": b"\b", b"f": b"\f",
                    b"(": b"(", b")": b")", b"\\": b"\\",
                }[nxt])
                i += 2
                continue
            if 48 <= nxt[0] <= 57:
                j = i + 1
                octal = b""
                while j < len(s) and len(octal) < 3 and 48 <= s[j] <= 57:
                    octal += s[j:j + 1]
                    j += 1
                out.append(int(octal, 8) & 0xFF)
                i = j
                continue
            out.extend(nxt)
            i += 2
            continue
        out.append(s[i])
        i += 1
    return bytes(out)


def _iter_text_operands(content: bytes) -> list[bytes]:
    """Return decoded operand payloads for Tj (paren + hex). Excludes TJ arrays."""
    out: list[bytes] = []
    for m in _PAREN_TJ_RE.finditer(content):
        try:
            out.append(_decode_pdf_string(m.group(1)))
        except Exception:
            continue
    for m in _HEX_TJ_RE.finditer(content):
        hx = m.group(1)
        if len(hx) % 2:
            hx = hx + b"0"
        try:
            out.append(bytes.fromhex(hx.decode("ascii")))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Alfa
# ---------------------------------------------------------------------------

def check_alfa_font_reassembly(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> RebuildResult:
    out = RebuildResult()
    if not producer and not creator:
        producer, creator = _producer_creator(pdf_bytes)
    emitter_ok = is_alfa_oracle_or_quartz(producer, creator)
    out.stats["emitter_oracle_or_quartz"] = emitter_ok
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    fonts: list[tuple[str, bytes]] = []
    for role in ("F1", "G1"):
        blob = _extract_fontfile2(pdf_bytes, role)
        if blob:
            fonts.append((role, blob))
    if not fonts:
        for i, blob in enumerate(_extract_font_programs(pdf_bytes) or []):
            fonts.append((f"#{i}", blob))

    fps = []
    for role, ttf in fonts:
        fp = structural_fingerprint(ttf)
        fp["role"] = role
        fps.append(fp)
        created, modified = fp["created"], fp["modified"]
        out.stats.setdefault("fonts", []).append(fp)

        if not emitter_ok or created is None or modified is None:
            continue

        # Source-font identity: Alfa bank font created epoch.
        if created == ALFA_HEAD_CREATED and modified != ALFA_HEAD_MODIFIED:
            detail = (
                f"{role} head.created={created} (Alfa source epoch) but "
                f"head.modified={modified} ≠ {ALFA_HEAD_MODIFIED}"
            )
            out.flags.append(_f(
                "ALFA_REBUILD_TTF_HEAD_EPOCH_001", detail,
                rule_id="K-ALFA-REBUILD-TTF-HEAD-EPOCH-001",
            ))
            out.flags.append(_f(
                "ALFA_REBUILD_FONT_EPOCH_PDF_TIME_CONFLICT_002",
                detail + "; head.modified is static source-font timestamp, "
                "not operation date — drift implies third-party rebuilder",
                rule_id="K-ALFA-REBUILD-FONT-EPOCH-PDF-TIME-002",
            ))
            out.flags.append(_f(
                "ALFA_REBUILD_TTF_MODIFIED_VARIABILITY_005",
                f"{role} created={ALFA_HEAD_CREATED} allows only "
                f"modified={ALFA_HEAD_MODIFIED}, got {modified}",
                rule_id="K-ALFA-REBUILD-TTF-MODIFIED-VARIABILITY-005",
            ))
            ok_loca, loca_msg = loca_glyf_consistent(ttf)
            rebuilt_glyf = (not ok_loca) or (
                fp["glyf_sha12"] and True  # glyf always present when rebuilt
            )
            # Subset source identity: same source epoch + non-canonical modified
            # + loca/glyf present (rebuilt subset payload).
            if rebuilt_glyf:
                out.flags.append(_f(
                    "ALFA_REBUILD_SUBSET_SOURCE_IDENTITY_003",
                    f"{role} source-font identity preserved (created="
                    f"{ALFA_HEAD_CREATED}) with non-canonical modified="
                    f"{modified}, loca/glyf payload rebuilt ({loca_msg})",
                    rule_id="K-ALFA-REBUILD-SUBSET-SOURCE-IDENTITY-003",
                ))

        # Emitter shell vs font lifecycle mismatch.
        if emitter_ok and created not in (None, ALFA_HEAD_CREATED):
            out.flags.append(_f(
                "ALFA_REBUILD_EMITTER_FONT_LIFECYCLE_004",
                f"Oracle/Quartz shell but embedded TTF head.created="
                f"{created} is not Alfa source epoch {ALFA_HEAD_CREATED}",
                rule_id="K-ALFA-REBUILD-EMITTER-FONT-LIFECYCLE-004",
            ))
        elif emitter_ok and created == ALFA_HEAD_CREATED and modified != ALFA_HEAD_MODIFIED:
            out.flags.append(_f(
                "ALFA_REBUILD_EMITTER_FONT_LIFECYCLE_004",
                f"Oracle/Quartz shell with Alfa created epoch but foreign "
                f"modified={modified} (expected {ALFA_HEAD_MODIFIED})",
                rule_id="K-ALFA-REBUILD-EMITTER-FONT-LIFECYCLE-004",
            ))

    out.stats["font_fingerprints"] = fps
    return out


# ---------------------------------------------------------------------------
# Sber
# ---------------------------------------------------------------------------

def _sber_cmap(pdf_bytes: bytes) -> dict[int, str]:
    try:
        from .font_layers import _font_objects
        fonts, _ = _font_objects(pdf_bytes)
        f1 = fonts.get("F1") or next(iter(fonts.values()), None)
        return dict((f1 or {}).get("cmap") or {})
    except Exception:
        return {}


def check_sber_font_reassembly(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
    profile_id: str = "",
) -> RebuildResult:
    out = RebuildResult()
    if not producer and not creator:
        producer, creator = _producer_creator(pdf_bytes)
    out.stats["producer"] = producer
    out.stats["creator"] = creator
    out.stats["profile_id"] = profile_id

    content = content_stream_bytes(pdf_bytes) or b""
    cmap = _sber_cmap(pdf_bytes)
    operands = _iter_text_operands(content)

    # 1) RAW NUL / unpaired units in Tj operands (Identity-H aware).
    for raw in operands:
        if len(raw) % 2 == 1:
            out.flags.append(_f(
                "SBER_REBUILD_RAW_NUL_IN_TEXT_001",
                f"Tj operand length {len(raw)} is odd — unpaired CID unit "
                f"(possible embedded NUL/control framing)",
                rule_id="K-SBER-REBUILD-RAW-NUL-IN-TEXT-001",
            ))
            out.flags.append(_f(
                "SBER_REBUILD_TEXT_OPERAND_CONTROL_BYTE_005",
                "unpaired UTF-16/CID unit in visible Tj operand",
                rule_id="K-SBER-REBUILD-TEXT-OPERAND-CONTROL-BYTE-005",
            ))
            break
        # Identity-H: scan CID→Unicode NUL
        nul_cids = []
        for i in range(0, len(raw), 2):
            cid = int.from_bytes(raw[i:i + 2], "big")
            ch = cmap.get(cid)
            if cid == 0 or ch == "\x00":
                nul_cids.append(cid)
            elif ch and len(ch) == 1 and ord(ch) < 32 and ch not in "\t\n\r":
                out.flags.append(_f(
                    "SBER_REBUILD_TEXT_OPERAND_CONTROL_BYTE_005",
                    f"control mapped CID {cid} → {ch!r} in visible Tj",
                    rule_id="K-SBER-REBUILD-TEXT-OPERAND-CONTROL-BYTE-005",
                ))
                break
        if nul_cids:
            out.flags.append(_f(
                "SBER_REBUILD_RAW_NUL_IN_TEXT_001",
                f"visible Tj maps CID→NUL ({nul_cids[:8]})",
                rule_id="K-SBER-REBUILD-RAW-NUL-IN-TEXT-001",
            ))
            out.flags.append(_f(
                "SBER_REBUILD_TEXT_OPERAND_CONTROL_BYTE_005",
                f"CID→NUL mapping in text operand: {nul_cids[:8]}",
                rule_id="K-SBER-REBUILD-TEXT-OPERAND-CONTROL-BYTE-005",
            ))

    # Font structural fingerprint + cross-product with content skeleton.
    fonts = _extract_font_programs(pdf_bytes) or []
    skeleton = content_skeleton_hash(pdf_bytes) or ""
    out.stats["content_skeleton"] = skeleton
    fps = []
    for i, ttf in enumerate(fonts):
        fp = structural_fingerprint(ttf)
        fp["role"] = f"F{i + 1}" if i == 0 else f"#{i}"
        fps.append(fp)
        created, modified = fp["created"], fp["modified"]
        ng = fp["numGlyphs"]
        ok_loca, loca_msg = loca_glyf_consistent(ttf)
        nonempty = nonempty_glyph_count(ttf)
        fp["loca_ok"] = ok_loca
        fp["loca_msg"] = loca_msg
        fp["nonempty_glyphs"] = nonempty

        # 4) Full-font cardinality (ArialMT profile numGlyphs==3419).
        if ng == SBER_FULL_NUMGLYPHS:
            if not ok_loca:
                out.flags.append(_f(
                    "SBER_REBUILD_USED_GLYPH_SUBSET_CARDINALITY_003",
                    f"numGlyphs=3419 but loca/glyf inconsistent: {loca_msg}",
                    rule_id="K-SBER-REBUILD-USED-GLYPH-SUBSET-CARDINALITY-003",
                ))
            elif (
                created == SBER_HEAD_CREATED
                and modified == SBER_HEAD_MODIFIED
                and fp["struct_fp"]
                and fp["struct_fp"] != SBER_FONT_STRUCT_FP
            ):
                out.flags.append(_f(
                    "SBER_REBUILD_USED_GLYPH_SUBSET_CARDINALITY_003",
                    f"numGlyphs=3419 with Sber head epoch but foreign "
                    f"struct_fp={fp['struct_fp']} (canon {SBER_FONT_STRUCT_FP})",
                    rule_id="K-SBER-REBUILD-USED-GLYPH-SUBSET-CARDINALITY-003",
                ))

        # 3) Content × font cross-product.
        if (
            is_sber_jasper(producer, creator)
            and skeleton
            and fp["struct_fp"]
            and fp["struct_fp"] != SBER_FONT_STRUCT_FP
        ):
            out.flags.append(_f(
                "SBER_REBUILD_CONTENT_FONT_CROSSPRODUCT_002",
                f"Jasper content skeleton={skeleton} paired with foreign font "
                f"struct_fp={fp['struct_fp']} (canon {SBER_FONT_STRUCT_FP})",
                rule_id="K-SBER-REBUILD-CONTENT-FONT-CROSSPRODUCT-002",
            ))

        # 5) Jasper object/font family conflict: jasper shell + non-Sber font epoch.
        if is_sber_jasper(producer, creator):
            if created and created != SBER_HEAD_CREATED:
                out.flags.append(_f(
                    "SBER_REBUILD_JASPER_OBJECT_FAMILY_CONFLICT_004",
                    f"Jasper/iText shell but font head.created={created} "
                    f"≠ Sber source {SBER_HEAD_CREATED}",
                    rule_id="K-SBER-REBUILD-JASPER-OBJECT-FAMILY-CONFLICT-004",
                ))
            elif (
                created == SBER_HEAD_CREATED
                and modified == SBER_HEAD_MODIFIED
                and fp["struct_fp"] != SBER_FONT_STRUCT_FP
            ):
                out.flags.append(_f(
                    "SBER_REBUILD_JASPER_OBJECT_FAMILY_CONFLICT_004",
                    f"Jasper object family with Sber head epoch but incompatible "
                    f"program tables struct_fp={fp['struct_fp']}",
                    rule_id="K-SBER-REBUILD-JASPER-OBJECT-FAMILY-CONFLICT-004",
                ))

    out.stats["font_fingerprints"] = fps
    return out


# ---------------------------------------------------------------------------
# T-Bank
# ---------------------------------------------------------------------------

def _tbank_role_fonts(pdf_bytes: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for role in ("F1", "F2", "F3"):
        blob = _extract_fontfile2(pdf_bytes, role)
        if blob:
            out[role] = blob
    return out


def _subsetter_cogeneration_fp(ttf: bytes) -> str:
    """Fingerprint of subsetter mechanics shared across F1/F2 when co-generated."""
    tables = parse_ttf_tables(ttf)
    created, modified = head_timestamps(ttf)
    order = list(tables)
    pad_key = []
    # crude padding profile between consecutive tables via sfnt offsets
    raw_tables = _ttf_tables(ttf)
    items = sorted(((off, tag, ln) for tag, (off, ln) in raw_tables.items()), key=lambda x: x[0])
    for i in range(len(items) - 1):
        off, tag, ln = items[i]
        next_off = items[i + 1][0]
        gap = next_off - (off + ln)
        pad_key.append(f"{tag.decode('latin1','replace')}->{items[i+1][1].decode('latin1','replace')}:{gap}")
    payload = "|".join([
        ",".join(order),
        f"cr={created}",
        f"mo={modified}",
        _sha16(tables.get("fpgm") or b""),
        _sha16(tables.get("prep") or b""),
        _sha16(tables.get("cvt ") or b""),
        ";".join(pad_key),
    ])
    return _sha16(payload.encode("utf-8"))


def check_tbank_font_reassembly(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
    reassembled_stats: dict[str, Any] | None = None,
) -> RebuildResult:
    out = RebuildResult()
    if not producer and not creator:
        producer, creator = _producer_creator(pdf_bytes)
    out.stats["producer"] = producer
    out.stats["creator"] = creator

    try:
        from .tbank_jasper_profile import claims_confirmed_tbank_profile
        profile_ok = claims_confirmed_tbank_profile(
            pdf_bytes, producer=producer, creator=creator,
        )
    except Exception:
        profile_ok = is_tbank_jasper_openpdf(producer, creator)
    out.stats["confirmed_tbank_profile"] = profile_ok

    roles = _tbank_role_fonts(pdf_bytes)
    fps: dict[str, dict[str, Any]] = {}
    for role, ttf in roles.items():
        fp = structural_fingerprint(ttf)
        fp["role"] = role
        fp["cogeneration_fp"] = _subsetter_cogeneration_fp(ttf)
        fps[role] = fp
    out.stats["font_fingerprints"] = fps
    out.stats["roles"] = sorted(roles)

    if not profile_ok:
        return out

    # Source-font head epoch (Alfa-analogue): native Jasper/OpenPDF subsets keep
    # frozen TinkoffSans head.created+modified. SEQ rebuilders copy created but
    # rewrite modified near generation time (CLEAN 180640/758/760/812: F1
    # modified≈3868529xxx vs corpus constant 3722743619 on n=128).
    f1_fp = fps.get("F1") or {}
    if (
        f1_fp.get("created") == TBANK_F1_CREATED
        and f1_fp.get("modified") is not None
        and f1_fp.get("modified") != TBANK_F1_MODIFIED
    ):
        out.flags.append(_f(
            "TBANK_F1_HEAD_MODIFIED_EPOCH",
            (
                f"F1 head.created={f1_fp.get('created')} (TinkoffSans source) "
                f"but head.modified={f1_fp.get('modified')} ≠ "
                f"{TBANK_F1_MODIFIED}"
            ),
            rule_id="K-TBANK-F1-HEAD-MODIFIED-EPOCH-001",
        ))
    f2_fp = fps.get("F2") or {}
    if (
        f2_fp.get("created") == TBANK_F2_CREATED
        and f2_fp.get("modified") is not None
        and f2_fp.get("modified") != TBANK_F2_MODIFIED
    ):
        out.flags.append(_f(
            "TBANK_F2_HEAD_MODIFIED_EPOCH",
            (
                f"F2 head.created={f2_fp.get('created')} (TinkoffSansBold source) "
                f"but head.modified={f2_fp.get('modified')} ≠ "
                f"{TBANK_F2_MODIFIED}"
            ),
            rule_id="K-TBANK-F2-HEAD-MODIFIED-EPOCH-001",
        ))

    if not {"F1", "F2", "F3"} <= set(roles):
        return out

    f1, f2, f3 = fps["F1"], fps["F2"], fps["F3"]
    f3_static = (
        f3.get("created") == TBANK_F3_CREATED
        and f3.get("modified") == TBANK_F3_MODIFIED
        and f3.get("glyf_sha12") == TBANK_F3_GLYF_SHA12
    )
    f1_frozen = (
        f1.get("created") == TBANK_F1_CREATED
        and f1.get("modified") == TBANK_F1_MODIFIED
    )
    f2_frozen = (
        f2.get("created") == TBANK_F2_CREATED
        and f2.get("modified") == TBANK_F2_MODIFIED
    )
    out.stats["f3_static"] = f3_static
    out.stats["f1_frozen_head"] = f1_frozen
    out.stats["f2_frozen_head"] = f2_frozen

    # Prefer evidence already computed by the pipeline (avoid double work).
    reassembled = False
    if reassembled_stats is not None:
        evid = (reassembled_stats or {}).get("evidence") or {}
        out.stats["reassembled_evidence"] = evid
        reassembled = bool(
            evid.get("E1") and evid.get("E2") and evid.get("E3")
            and evid.get("E4") and (evid.get("E5_v2") or evid.get("E5_v1"))
        )
    else:
        try:
            from .tbank_reassembled_subset import check_reassembled_bank_assets
            rr = check_reassembled_bank_assets(
                pdf_bytes, producer=producer, creator=creator,
            )
            evid = dict((rr.stats or {}).get("evidence") or {})
            out.stats["reassembled_evidence"] = evid
            reassembled = bool(
                evid.get("E1") and evid.get("E2") and evid.get("E3")
                and evid.get("E4") and (evid.get("E5_v2") or evid.get("E5_v1"))
            )
        except Exception as exc:
            out.stats["reassembled_error"] = str(exc)[:160]

    if not reassembled:
        return out

    cogeneration = f1.get("cogeneration_fp") == f2.get("cogeneration_fp")
    detail_base = (
        f"F3 static={f3_static} glyf={f3.get('glyf_sha12')}; "
        f"F1 head=({f1.get('created')},{f1.get('modified')}) "
        f"glyf={f1.get('glyf_sha12')}; "
        f"F2 head=({f2.get('created')},{f2.get('modified')}) "
        f"glyf={f2.get('glyf_sha12')}; "
        f"cogeneration_fp_match={cogeneration}"
    )

    if f3_static and f1_frozen and f2_frozen:
        out.flags.append(_f(
            "TBANK_REBUILD_FONT_DUAL_DYNAMIC_001",
            "F1+F2 dual-dynamic foreign subsetter with staff F3 static asset; "
            + detail_base,
            rule_id="K-TBANK-REBUILD-FONT-DUAL-DYNAMIC-001",
        ))
        out.flags.append(_f(
            "TBANK_REBUILD_STATIC_F3_DYNAMIC_F12_SPLIT_002",
            "asymmetric split: F3 staff-static, F1/F2 glyf/loca rebuilt; "
            + detail_base,
            rule_id="K-TBANK-REBUILD-STATIC-F3-DYNAMIC-F12-SPLIT-002",
        ))
        out.flags.append(_f(
            "TBANK_REBUILD_GLYPH_PAYLOAD_WITH_FROZEN_HEAD_003",
            "F1/F2 preserve exact source head.created/modified but glyf/loca "
            "payload is foreign subsetter; " + detail_base,
            rule_id="K-TBANK-REBUILD-GLYPH-PAYLOAD-WITH-FROZEN-HEAD-003",
        ))
        if cogeneration:
            out.flags.append(_f(
                "TBANK_REBUILD_F1_F2_COGENERATION_004",
                f"F1 and F2 share unconfirmed subsetter cogeneration_fp="
                f"{f1.get('cogeneration_fp')}; " + detail_base,
                rule_id="K-TBANK-REBUILD-F1-F2-COGENERATION-004",
            ))
        if is_tbank_jasper_openpdf(producer, creator):
            out.flags.append(_f(
                "TBANK_REBUILD_CANONICAL_SHELL_FOREIGN_SUBSETTER_005",
                "JasperReports 6.20.3 / OpenPDF 1.3.30 shell + staff F3/images "
                "with foreign F1/F2 subsetter fingerprint; " + detail_base,
                rule_id="K-TBANK-REBUILD-CANONICAL-SHELL-FOREIGN-SUBSETTER-005",
            ))
    return out


# ---------------------------------------------------------------------------
# Unified entry
# ---------------------------------------------------------------------------

def check_embedded_font_reassembly(
    pdf_bytes: bytes,
    *,
    bank: str,
    producer: str = "",
    creator: str = "",
    profile_id: str = "",
    reassembled_stats: dict[str, Any] | None = None,
) -> RebuildResult:
    bank = (bank or "").lower()
    try:
        if bank in {"alfa", "alfabank", "alpha"}:
            return check_alfa_font_reassembly(
                pdf_bytes, producer=producer, creator=creator,
            )
        if bank in {"sber", "sberbank"}:
            return check_sber_font_reassembly(
                pdf_bytes,
                producer=producer,
                creator=creator,
                profile_id=profile_id,
            )
        if bank in {"tbank", "tinkoff", "t-bank"}:
            return check_tbank_font_reassembly(
                pdf_bytes,
                producer=producer,
                creator=creator,
                reassembled_stats=reassembled_stats,
            )
        out = RebuildResult()
        out.stats["skipped"] = f"unknown_bank:{bank}"
        return out
    except Exception as exc:
        out = RebuildResult(analysis_ok=False)
        out.stats["error"] = str(exc)[:240]
        return out
