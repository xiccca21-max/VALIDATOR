"""Bank-agnostic SFNT mathematical integrity (checksum / directory).

Does NOT flag unknown fonts or novel subsets — only objectively broken SFNT.
Reuses parse helpers from tbank_sfnt_table_integrity (no duplicate inventory HARD).
"""

from __future__ import annotations

import re
import struct
import zlib

from .structural_deep_xref_stream import DeepAuditResult, StructFinding
from .tbank_sfnt_table_integrity import _calc_table_checksum, parse_sfnt_directory

_FONTFILE_RE = re.compile(
    rb"/FontFile2\s+(\d+)\s+(\d+)\s+R|/FontFile3\s+(\d+)\s+(\d+)\s+R|"
    rb"/FontFile\s+(\d+)\s+(\d+)\s+R"
)
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)


def _extract_stream_payload(obj: bytes) -> bytes | None:
    sm = re.search(rb"stream\r?\n", obj)
    if not sm:
        return None
    hdr = obj[: sm.start()]
    start = sm.end()
    es = obj.find(b"endstream", start)
    if es < 0:
        return None
    raw = obj[start:es]
    lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", hdr)
    if lm:
        ln = int(lm.group(1))
        raw = obj[start : start + ln]
    if b"/FlateDecode" in hdr or b"/Flate" in hdr:
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw
    return raw


def _iter_embedded_sfnt(pdf_bytes: bytes) -> list[tuple[int, bytes]]:
    """Return (object_number, ttf_bytes) for FontFile* streams and SFNT magic."""
    out: list[tuple[int, bytes]] = []
    objs = {
        (int(m.group(1)), int(m.group(2))): m.group(0)
        for m in _OBJ_RE.finditer(pdf_bytes)
    }
    refs: set[int] = set()
    for m in _FONTFILE_RE.finditer(pdf_bytes):
        for g in m.groups():
            if g is not None:
                refs.add(int(g))
                break

    for (num, _gen), body in objs.items():
        payload = _extract_stream_payload(body)
        if not payload:
            continue
        if payload[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            out.append((num, payload))
    return out


def _verify_sfnt(ttf: bytes, objnum: int, res: DeepAuditResult) -> None:
    _header, records, errors = parse_sfnt_directory(ttf)
    for e in errors:
        res.add(StructFinding(
            code="SFNT_DIRECTORY_CONTRADICTION",
            detail=f"FontFile obj {objnum}: {e}",
            object_number=objnum,
            expected="valid SFNT directory",
            actual=e,
            parser_stage="sfnt_math.directory",
        ))

    for rec in records:
        if rec.offset + rec.length > len(ttf):
            continue
        payload = bytearray(ttf[rec.offset : rec.offset + rec.length])
        if rec.tag == b"head" and len(payload) >= 12:
            payload[8:12] = b"\x00\x00\x00\x00"
        calc = _calc_table_checksum(bytes(payload))
        if calc != rec.checksum:
            res.add(StructFinding(
                code="SFNT_TABLE_CHECKSUM_INVALID",
                detail=(
                    f"FontFile obj {objnum}: table {rec.tag!r} checksum "
                    f"dir={rec.checksum:#x} calc={calc:#x}"
                ),
                object_number=objnum,
                expected=hex(rec.checksum),
                actual=hex(calc),
                parser_stage="sfnt_math.table_checksum",
            ))

    if len(ttf) >= 12 and records:
        tmp = bytearray(ttf)
        head_rec = next((r for r in records if r.tag == b"head"), None)
        if head_rec and head_rec.offset + 12 <= len(tmp):
            stored_adj = struct.unpack(
                ">I", bytes(tmp[head_rec.offset + 8 : head_rec.offset + 12])
            )[0]
            tmp[head_rec.offset + 8 : head_rec.offset + 12] = b"\x00\x00\x00\x00"
            total = _calc_table_checksum(bytes(tmp))
            expected_adj = (0xB1B0AFBA - total) & 0xFFFFFFFF
            if stored_adj != expected_adj:
                res.add(StructFinding(
                    code="SFNT_CHECKSUM_ADJUSTMENT_INVALID",
                    detail=(
                        f"FontFile obj {objnum}: head.checkSumAdjustment "
                        f"stored={stored_adj:#x} expected={expected_adj:#x}"
                    ),
                    object_number=objnum,
                    expected=hex(expected_adj),
                    actual=hex(stored_adj),
                    parser_stage="sfnt_math.adjustment",
                ))

    tags = {r.tag: r for r in records}
    if b"loca" in tags and b"glyf" in tags and b"head" in tags and b"maxp" in tags:
        try:
            head = ttf[tags[b"head"].offset : tags[b"head"].offset + tags[b"head"].length]
            maxp = ttf[tags[b"maxp"].offset : tags[b"maxp"].offset + tags[b"maxp"].length]
            loca = ttf[tags[b"loca"].offset : tags[b"loca"].offset + tags[b"loca"].length]
            glyf = ttf[tags[b"glyf"].offset : tags[b"glyf"].offset + tags[b"glyf"].length]
            if len(head) >= 52 and len(maxp) >= 6:
                index_to_loc = struct.unpack(">H", head[50:52])[0]
                num_glyphs = struct.unpack(">H", maxp[4:6])[0]
                if index_to_loc == 0:
                    need = (num_glyphs + 1) * 2
                    offs = (
                        [
                            struct.unpack(">H", loca[i : i + 2])[0] * 2
                            for i in range(0, need, 2)
                        ]
                        if len(loca) >= need
                        else []
                    )
                    if len(loca) < need:
                        res.add(StructFinding(
                            code="SFNT_DIRECTORY_CONTRADICTION",
                            detail=(
                                f"FontFile obj {objnum}: short loca for "
                                f"numGlyphs={num_glyphs}"
                            ),
                            object_number=objnum,
                            parser_stage="sfnt_math.loca",
                        ))
                else:
                    need = (num_glyphs + 1) * 4
                    if len(loca) < need:
                        res.add(StructFinding(
                            code="SFNT_DIRECTORY_CONTRADICTION",
                            detail=(
                                f"FontFile obj {objnum}: short long loca for "
                                f"numGlyphs={num_glyphs}"
                            ),
                            object_number=objnum,
                            parser_stage="sfnt_math.loca",
                        ))
                        offs = []
                    else:
                        offs = [
                            struct.unpack(">I", loca[i : i + 4])[0]
                            for i in range(0, need, 4)
                        ]
                if offs:
                    if any(offs[i] > offs[i + 1] for i in range(len(offs) - 1)):
                        res.add(StructFinding(
                            code="SFNT_DIRECTORY_CONTRADICTION",
                            detail=f"FontFile obj {objnum}: loca offsets not monotonic",
                            object_number=objnum,
                            parser_stage="sfnt_math.loca_mono",
                        ))
                    if offs[-1] > len(glyf):
                        res.add(StructFinding(
                            code="SFNT_DIRECTORY_CONTRADICTION",
                            detail=(
                                f"FontFile obj {objnum}: loca end {offs[-1]} > "
                                f"glyf len {len(glyf)}"
                            ),
                            object_number=objnum,
                            parser_stage="sfnt_math.loca_glyf",
                        ))
        except Exception as exc:
            res.add(StructFinding(
                code="SFNT_DIRECTORY_CONTRADICTION",
                detail=f"FontFile obj {objnum}: loca/glyf check error {exc}",
                object_number=objnum,
                parser_stage="sfnt_math.loca_exc",
            ))


def audit_sfnt_math(pdf_bytes: bytes) -> DeepAuditResult:
    res = DeepAuditResult()
    fonts = _iter_embedded_sfnt(pdf_bytes)
    res.stats["sfnt_fonts"] = len(fonts)
    for objnum, ttf in fonts:
        _verify_sfnt(ttf, objnum, res)
    return res
