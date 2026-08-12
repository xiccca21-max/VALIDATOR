"""Per-stream FlateDecode profile collection for T-Bank serializer provenance."""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
import zlib as _zlib_mod
from dataclasses import dataclass, field
from enum import Enum

from .java_deflater import java_canonical_match, java_deflate, java_match_via_files

_OBJ_BODY_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.DOTALL)
_STREAM_KW_RE = re.compile(rb">>\s*stream\r?\n")
_STREAM_LEN_RE = re.compile(rb"/Length\s+(\d+)")
_INT_OBJ_RE = re.compile(rb"(\d+)\s+0\s+obj\s+(\d+)\s+endobj")


class StreamRole(str, Enum):
    PAGE_CONTENT = "page content"
    FONT = "font"
    TOUNICODE = "ToUnicode"
    IMAGE = "image"
    OTHER = "other"


@dataclass
class DeflateBlock:
    bfinal: int
    btype: int


@dataclass
class FlateStreamProfile:
    object_number: int
    generation: int
    role: StreamRole
    resource_role: str
    pdf_offset: int
    declared_length: int | None
    compressed_length: int
    compressed_sha256: str
    decoded_sha256: str
    decoded_length: int
    cmf: int
    flg: int
    deflate_blocks: list[DeflateBlock] = field(default_factory=list)
    huffman_fingerprint: str = ""
    adler32: int = 0
    eof_clean: bool = True
    unused_tail: int = 0
    unconsumed_tail: bytes = b""
    canonical_match: bool = False
    canonical_length: int = 0
    canonical_sha256: str = ""
    first_diff_offset: int = -1
    first_diff_actual: int = -1
    first_diff_expected: int = -1
    second_analyzer_pass: bool = False
    raw_compressed: bytes = b""
    decoded: bytes = b""


def _indirect_lengths(pdf_bytes: bytes) -> dict[int, int]:
    return {int(m.group(1)): int(m.group(2)) for m in _INT_OBJ_RE.finditer(pdf_bytes)}


def _length_from_hdr(hdr: bytes, indirect: dict[int, int]) -> int | None:
    m = re.search(rb"/Length\s+(\d+)\s+0\s+R", hdr)
    if m:
        return indirect.get(int(m.group(1)))
    m = _STREAM_LEN_RE.search(hdr)
    return int(m.group(1)) if m else None


def _classify_role(hdr: bytes, decoded: bytes) -> StreamRole:
    if b"/Subtype /Image" in hdr or b"/Subtype/Image" in hdr:
        return StreamRole.IMAGE
    if b"/FontFile2" in hdr or b"/FontFile3" in hdr:
        return StreamRole.FONT
    if decoded and (b"beginbfchar" in decoded or b"beginbfrange" in decoded):
        return StreamRole.TOUNICODE
    if decoded and b"BT" in decoded and (b"Tj" in decoded or b"TJ" in decoded) and b"Tm" in decoded:
        return StreamRole.PAGE_CONTENT
    if decoded[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO", b"ttcf") and len(decoded) > 500:
        return StreamRole.FONT
    return StreamRole.OTHER


def _precise_resource_roles(pdf_bytes: bytes) -> dict[int, str]:
    """Resolve F1/F2/F3 FontFile2 and ToUnicode stream object numbers."""
    objects = {
        int(m.group(1)): m.group(3)
        for m in _OBJ_BODY_RE.finditer(pdf_bytes)
    }
    roles: dict[int, str] = {}
    for font_name, font_obj_raw in re.findall(
        rb"/(F[123])\s+(\d+)\s+0\s+R",
        pdf_bytes,
    ):
        layer = font_name.decode("ascii")
        font_obj = int(font_obj_raw)
        body = objects.get(font_obj, b"")

        to_unicode = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if to_unicode:
            roles[int(to_unicode.group(1))] = f"{layer} ToUnicode"

        descendant = re.search(
            rb"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R",
            body,
        )
        font_body = objects.get(int(descendant.group(1)), b"") if descendant else body
        descriptor = re.search(
            rb"/FontDescriptor\s+(\d+)\s+0\s+R",
            font_body,
        )
        descriptor_body = (
            objects.get(int(descriptor.group(1)), b"")
            if descriptor
            else font_body
        )
        font_file = re.search(
            rb"/FontFile(?:2|3)\s+(\d+)\s+0\s+R",
            descriptor_body,
        )
        if font_file:
            roles[int(font_file.group(1))] = f"{layer} FontFile2"
    return roles


def _read_bits(data: bytes, bitpos: int, n: int) -> tuple[int, int]:
    val = 0
    for i in range(n):
        byte_i = (bitpos + i) // 8
        bit_i = (bitpos + i) % 8
        if byte_i >= len(data):
            return val, bitpos + i
        val |= ((data[byte_i] >> bit_i) & 1) << i
    return val, bitpos + n


def _parse_deflate_blocks(deflate_data: bytes) -> tuple[list[DeflateBlock], str]:
    """Raw DEFLATE block sequence + dynamic Huffman fingerprint."""
    blocks: list[DeflateBlock] = []
    fingerprint_parts: list[str] = []
    bitpos = 0
    while bitpos < len(deflate_data) * 8:
        bfinal, bitpos = _read_bits(deflate_data, bitpos, 1)
        btype, bitpos = _read_bits(deflate_data, bitpos, 2)
        blocks.append(DeflateBlock(bfinal=bfinal, btype=btype))
        if btype == 0:
            bitpos = ((bitpos + 7) // 8) * 8
            if bitpos // 8 + 4 > len(deflate_data):
                break
            ln = deflate_data[bitpos // 8] | (deflate_data[bitpos // 8 + 1] << 8)
            bitpos += 32 + ln * 8
        elif btype == 1:
            break
        elif btype == 2:
            hlit, bitpos = _read_bits(deflate_data, bitpos, 5)
            hdist, bitpos = _read_bits(deflate_data, bitpos, 5)
            hclen, bitpos = _read_bits(deflate_data, bitpos, 4)
            hlit += 257
            hdist += 1
            hclen += 4
            cl_order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
            clens: list[int] = []
            for i in range(hclen):
                v, bitpos = _read_bits(deflate_data, bitpos, 3)
                clens.append(v)
            ordered = [0] * 19
            for i, idx in enumerate(cl_order[:hclen]):
                if i < len(clens):
                    ordered[idx] = clens[i]
            fingerprint_parts.append(
                f"hlit={hlit}:hdist={hdist}:clen={','.join(str(x) for x in ordered)}"
            )
            break
        else:
            break
        if bfinal:
            break
    fp = hashlib.sha256("|".join(fingerprint_parts).encode()).hexdigest()[:16] if fingerprint_parts else ""
    if not fp and blocks:
        fp = hashlib.sha256(
            ",".join(f"{b.bfinal}:{b.btype}" for b in blocks).encode()
        ).hexdigest()[:16]
    return blocks, fp


def _zlib_profile(raw: bytes) -> tuple[int, int, int, list[DeflateBlock], str, bool, int, bytes]:
    if len(raw) < 2:
        return 0, 0, 0, [], "", False, 0, b""
    cmf, flg = raw[0], raw[1]
    dobj = _zlib_mod.decompressobj()
    try:
        decoded = dobj.decompress(raw)
    except Exception:
        decoded = b""
    unused = dobj.unused_data
    unconsumed = dobj.unconsumed_tail
    eof_clean = not unused and not unconsumed
    adler = 0
    if len(raw) >= 4:
        adler = struct.unpack(">I", b"\x00" + raw[-3:])[0] if False else 0
        adler = int.from_bytes(raw[-4:], "big") if len(decoded) > 0 else 0
    deflate_payload = raw[2:-4] if len(raw) >= 6 and decoded else raw[2:]
    blocks, fp = _parse_deflate_blocks(deflate_payload)
    return cmf, flg, adler, blocks, fp, eof_clean, len(unused), unconsumed


def _enumerate_flate_streams_uncached(pdf_bytes: bytes) -> list[FlateStreamProfile]:
    """Enumerate every FlateDecode stream with full serializer profile."""
    indirect = _indirect_lengths(pdf_bytes)
    resource_roles = _precise_resource_roles(pdf_bytes)
    seen: set[tuple[int, int]] = set()
    profiles: list[FlateStreamProfile] = []

    def _add(objn: int, gen: int, hdr: bytes, raw: bytes, pdf_off: int) -> None:
        key = (objn, gen)
        if key in seen:
            return
        seen.add(key)
        if not raw or raw[0:1] != b"\x78":
            return
        try:
            decoded = zlib.decompress(raw)
        except Exception:
            decoded = b""
        cmf, flg, adler, blocks, fp, eof_clean, unused, unconsumed = _zlib_profile(raw)
        # One JVM spawn per stream: reuse for match; file-path oracle only on mismatch.
        canon = java_deflate(decoded) if decoded else None
        match, diff_off, diff_a, diff_e = (
            java_canonical_match(raw, decoded, expected=canon)
            if decoded else (False, -1, -1, -1)
        )
        if decoded and not match:
            second_ok, _ = java_match_via_files(raw, decoded)
        else:
            # Canonical stdin path already agreed (or no payload) — no second JVM.
            second_ok = match
        declared = _length_from_hdr(hdr, indirect)
        profiles.append(FlateStreamProfile(
            object_number=objn,
            generation=gen,
            role=_classify_role(hdr, decoded),
            resource_role=resource_roles.get(objn, ""),
            pdf_offset=pdf_off,
            declared_length=declared,
            compressed_length=len(raw),
            compressed_sha256=hashlib.sha256(raw).hexdigest(),
            decoded_sha256=hashlib.sha256(decoded).hexdigest() if decoded else "",
            decoded_length=len(decoded),
            cmf=cmf,
            flg=flg,
            deflate_blocks=blocks,
            huffman_fingerprint=fp,
            adler32=adler,
            eof_clean=eof_clean,
            unused_tail=unused,
            unconsumed_tail=unconsumed,
            canonical_match=match,
            canonical_length=len(canon) if canon else 0,
            canonical_sha256=hashlib.sha256(canon).hexdigest() if canon else "",
            first_diff_offset=diff_off,
            first_diff_actual=diff_a,
            first_diff_expected=diff_e,
            second_analyzer_pass=second_ok == match,
            raw_compressed=raw,
            decoded=decoded,
        ))

    for m in _OBJ_BODY_RE.finditer(pdf_bytes):
        objn, gen = int(m.group(1)), int(m.group(2))
        body = m.group(3)
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            continue
        hdr = body[: sm.start()]
        start = sm.end()
        ln = _length_from_hdr(hdr, indirect)
        if ln and ln > 0:
            raw = body[start : start + ln]
        else:
            em = body.find(b"endstream", start)
            if em < 0:
                continue
            raw = body[start:em].rstrip(b"\r\n")
        pdf_off = m.start() + sm.end()
        _add(objn, gen, hdr, raw, pdf_off)

    for m in _STREAM_KW_RE.finditer(pdf_bytes):
        start = m.end()
        hdr = pdf_bytes[max(0, m.start() - 400) : m.start()]
        om = re.search(rb"(\d+)\s+(\d+)\s+obj", pdf_bytes[max(0, m.start() - 120) : m.start()])
        objn = int(om.group(1)) if om else -1
        gen = int(om.group(2)) if om else 0
        ln = _length_from_hdr(hdr, indirect)
        if ln and ln > 0:
            raw = pdf_bytes[start : start + ln]
        else:
            es = pdf_bytes.find(b"endstream", start)
            if es < 0:
                continue
            raw = pdf_bytes[start:es].rstrip(b"\r\n")
        _add(objn, gen, hdr, raw, start)

    profiles.sort(key=lambda p: p.object_number)
    return profiles


# Intra-/cross-caller cache: deflate + serializer + integrity all need the same pass.
_FLATE_CACHE: dict[str, list[FlateStreamProfile]] = {}
_FLATE_CACHE_ORDER: list[str] = []
_FLATE_CACHE_MAX = 4


def clear_flate_cache() -> None:
    _FLATE_CACHE.clear()
    _FLATE_CACHE_ORDER.clear()


def enumerate_flate_streams(pdf_bytes: bytes) -> list[FlateStreamProfile]:
    """Enumerate FlateDecode streams (cached by content hash for the request lifetime)."""
    key = hashlib.sha256(pdf_bytes).hexdigest()
    hit = _FLATE_CACHE.get(key)
    if hit is not None:
        return hit
    profiles = _enumerate_flate_streams_uncached(pdf_bytes)
    _FLATE_CACHE[key] = profiles
    _FLATE_CACHE_ORDER.append(key)
    while len(_FLATE_CACHE_ORDER) > _FLATE_CACHE_MAX:
        old = _FLATE_CACHE_ORDER.pop(0)
        _FLATE_CACHE.pop(old, None)
    return profiles