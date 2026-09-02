"""K-TBANK-REASSEMBLY-FAMILY-V3 — live HARD/KNOWN F1/F2 reconstructed-subset family.

Decisive code: TBANK_REASSEMBLY_FAMILY_V3 (KNOWN → immediate ФЕЙК).

Also emits independent HARD minimality / bijection / exact-closure codes for
Type0 F1/F2 under the same Jasper/OpenPDF SBP profile gate.

No shadow mode, no score accumulation, no identity blacklists.
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .corpus_profiles import CHANNEL_SBP, detect_receipt_channel
from .pdf_forensics import _ttf_tables
from .structure import content_stream_bytes, find_streams, is_content_stream
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

RULE_FAMILY = "K-TBANK-REASSEMBLY-FAMILY-V3-001"
RULE_CMAP = "A-TBANK-SUBSET-CMAP-MINIMALITY-001"
RULE_W = "A-TBANK-W-ARRAY-MINIMALITY-001"
RULE_W_ADV = "A-TBANK-W-TTF-ADVANCE-MISMATCH-001"
RULE_BIJ = "A-TBANK-CID-SERIALIZATION-BIJECTION-001"
RULE_CLOSURE = "A-TBANK-FONT-SUBSET-EXACT-CLOSURE-001"
RULE_ORPHAN_RESIDUE = "A-TBANK-FONT-SUBSET-ORPHAN-RESIDUE-001"

CODE_FAMILY = "TBANK_REASSEMBLY_FAMILY_V3"
CODE_CMAP = "TBANK_SUBSET_CMAP_NOT_MINIMAL"
CODE_W = "TBANK_W_ARRAY_NOT_MINIMAL"
CODE_W_ADV = "TBANK_W_TTF_ADVANCE_MISMATCH"
CODE_BIJ = "TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION"
CODE_CLOSURE = "TBANK_FONT_SUBSET_EXACT_CLOSURE"
CODE_ORPHAN_RESIDUE = "TBANK_FONT_SUBSET_ORPHAN_RESIDUE"
CODE_MAXP_RECOMPUTED = "TBANK_F1_MAXP_RECOMPUTED_TO_SUBSET"
RULE_MAXP_RECOMPUTED = "A-TBANK-F1-MAXP-RECOMPUTED-TO-SUBSET-001"
CODE_MAXP_COMPOSITE = "TBANK_F1_MAXP_COMPOSITE_ENVELOPE_MISMATCH"
RULE_MAXP_COMPOSITE = "A-TBANK-F1-MAXP-COMPOSITE-ENVELOPE-001"
CODE_HHEA_ENVELOPE = "TBANK_F1_HHEA_ENVELOPE_MISMATCH"
RULE_HHEA_ENVELOPE = "A-TBANK-F1-HHEA-ENVELOPE-001"
CODE_F2_HEAD_ENVELOPE = "TBANK_F2_HEAD_ENVELOPE_MISMATCH"
RULE_F2_HEAD_ENVELOPE = "A-TBANK-F2-HEAD-ENVELOPE-001"
CODE_F2_MAXP_ENVELOPE = "TBANK_F2_MAXP_ENVELOPE_MISMATCH"
RULE_F2_MAXP_ENVELOPE = "A-TBANK-F2-MAXP-ENVELOPE-001"
CODE_F1_HMTX_ENVELOPE = "TBANK_F1_HMTX_ENVELOPE_MISMATCH"
RULE_F1_HMTX_ENVELOPE = "A-TBANK-F1-HMTX-ENVELOPE-001"
CODE_F2_GLYF_PAD = "TBANK_F2_GLYF_LOCA_PADDING"
RULE_F2_GLYF_PAD = "A-TBANK-F2-GLYF-LOCA-PADDING-001"
CODE_F2_DIGIT_FAT = "TBANK_F2_GLYF_DIGIT_CARD_FAT"
RULE_F2_DIGIT_FAT = "A-TBANK-F2-GLYF-DIGIT-CARD-FAT-001"
CODE_F1_GLYF_SHAPE = "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH"
RULE_F1_GLYF_SHAPE = "A-TBANK-F1-GLYF-SHAPE-ENVELOPE-001"
CODE_F1_GLYF_SIZES = "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH"
RULE_F1_GLYF_SIZES = "A-TBANK-F1-GLYF-SIZE-MULTISET-001"

# Jasper F1.glyf length → allowed (composite, nonempty, simple, cmap) shapes
# on gated genuines (n=56). Includes rare multi-shape lengths 12328/13002.
# SEQ keeps donor glyf_len but swaps letter inventory → shape not in set.
_F1_GLYF_SHAPES_BY_LEN: dict[int, frozenset[tuple[int, int, int, int]]] = {
    12080: frozenset([(11, 75, 64, 66)]),
    12170: frozenset([(10, 74, 64, 65)]),
    12176: frozenset([(11, 76, 65, 67)]),
    12178: frozenset([(10, 75, 65, 66)]),
    12236: frozenset([(11, 76, 65, 69)]),
    12308: frozenset([(10, 75, 65, 66)]),
    12328: frozenset([(10, 75, 65, 66), (12, 77, 65, 67)]),
    12344: frozenset([(11, 76, 65, 67)]),
    12398: frozenset([(12, 78, 66, 68)]),
    12422: frozenset([(11, 77, 66, 67)]),
    12434: frozenset([(11, 77, 66, 68)]),
    12442: frozenset([(11, 77, 66, 67)]),
    12468: frozenset([(11, 77, 66, 68)]),
    12482: frozenset([(11, 77, 66, 67)]),
    12520: frozenset([(11, 78, 67, 69)]),
    12528: frozenset([(11, 77, 66, 68)]),
    12530: frozenset([(12, 78, 66, 67)]),
    12554: frozenset([(11, 78, 67, 68)]),
    12560: frozenset([(11, 77, 66, 68)]),
    12592: frozenset([(10, 76, 66, 67)]),
    12596: frozenset([(12, 79, 67, 68)]),
    12598: frozenset([(12, 79, 67, 68)]),
    12612: frozenset([(11, 78, 67, 72)]),
    12626: frozenset([(12, 79, 67, 68)]),
    12684: frozenset([(12, 79, 67, 69)]),
    12700: frozenset([(13, 80, 67, 68)]),
    12720: frozenset([(11, 79, 68, 69)]),
    12768: frozenset([(12, 79, 67, 69)]),
    12784: frozenset([(10, 78, 68, 69)]),
    12816: frozenset([(11, 79, 68, 69)]),
    12818: frozenset([(11, 79, 68, 71)]),
    12852: frozenset([(11, 79, 68, 71)]),
    12864: frozenset([(11, 78, 67, 68)]),
    12910: frozenset([(15, 83, 68, 71)]),
    12978: frozenset([(13, 81, 68, 67)]),
    13000: frozenset([(13, 81, 68, 70)]),
    13002: frozenset([(13, 82, 69, 68), (14, 83, 69, 71)]),
    13038: frozenset([(11, 78, 67, 68)]),
    13210: frozenset([(12, 81, 69, 70)]),
    13264: frozenset([(12, 82, 70, 73)]),
    13610: frozenset([(12, 84, 72, 75)]),
    13794: frozenset([(13, 86, 73, 76)]),
    14032: frozenset([(13, 86, 73, 76)]),
}

# sha256[:16] of str(sorted nonempty glyph byte-lengths) per F1.glyf_len.
# Same glyf_len can share shape counts after SEQ letter-swap, but the anonymous
# size multiset still drifts (0 FP on n=56; catches shape-matched CLEANs).
_F1_GLYF_SIZE_HASH_BY_LEN: dict[int, frozenset[str]] = {
    12080: frozenset(["167017bea02afff0"]),
    12170: frozenset(["4ea4714bf77a0acf"]),
    12176: frozenset(["babe761883d6ee12"]),
    12178: frozenset(["ed12cd9ad1310748"]),
    12236: frozenset(["095ae80d23a7f1aa"]),
    12308: frozenset(["d28cae048180afe9"]),
    12328: frozenset(["159825f7cf23186d", "17a427e8504e9168"]),
    12344: frozenset(["1517700889dac262"]),
    12398: frozenset(["225a3a8e25756145"]),
    12422: frozenset(["aa8885ac771fd453"]),
    12434: frozenset(["36ed273c798fb20d"]),
    12442: frozenset(["d2864460b6e232c8"]),
    12468: frozenset(["c31c760dc43702db"]),
    12482: frozenset(["c52968a43be28c0a"]),
    12520: frozenset(["3c01ee176caa983d"]),
    12528: frozenset(["ebe67cf294ebd429"]),
    12530: frozenset(["757c5cf7b473602c"]),
    12554: frozenset(["f8044e5351ddae9e"]),
    12560: frozenset(["bb3f6d757dfa85bf"]),
    12592: frozenset(["509e5fa177390434"]),
    12596: frozenset(["d6a46a194ae57213"]),
    12598: frozenset(["c9d52fe7b6d3b2e0"]),
    12612: frozenset(["a436c61d9b641f7c"]),
    12626: frozenset(["2b206e90f1ec9951"]),
    12684: frozenset(["b89a6cd28398ba3a"]),
    12700: frozenset(["d72076e39923e2a6"]),
    12720: frozenset(["54ef407ad07a8d8c"]),
    12768: frozenset(["42635ded87226ada"]),
    12784: frozenset(["a7123956e85551bd"]),
    12816: frozenset(["4a4af69efac5c302"]),
    12818: frozenset(["61abc5d0866a9634"]),
    12852: frozenset(["e5c3971754e7b214"]),
    12864: frozenset(["f69613bd0f38f47b"]),
    12910: frozenset(["36f3949c2a41579a"]),
    12978: frozenset(["c353daa9dd8e2fd5"]),
    13000: frozenset(["cd4eea85c192b792"]),
    13002: frozenset(["e2fbfe0fba87a702", "f2de94be210545d6"]),
    13038: frozenset(["7fd932caf3669f0f"]),
    13210: frozenset(["3e6d8fc36867abbc"]),
    13264: frozenset(["0706176f8158bbc0"]),
    13610: frozenset(["cc9b2db2c734332f"]),
    13794: frozenset(["9f94401fca3cfd15"]),
    14032: frozenset(["7bf3ef70e880e296"]),
}

# Full TinkoffSans Jasper maxp composite envelope (identical on all gated genuines).
_CANON_MAX_COMPOSITE_POINTS = 102
_CANON_MAX_COMPOSITE_CONTOURS = 4
# Full-font hhea blob (sha256[:16]) — identical on all gated genuines (n=56).
_CANON_F1_HHEA_SHA16 = "08c0a1c91858beca"
# Full TinkoffSans-Medium head blob (sha256[:16]) — identical on all gated
# genuines (n=56). SEQ rebuilds F2.glyf and rewrites head checkSumAdjustment
# (bytes 8–11) while keeping created/modified/bbox — competitors catch that.
_CANON_F2_HEAD_SHA16 = "d25ccb9e7b400baf"
# Full Medium maxp / F1 hmtx — identical on all gated genuines (n=56).
_CANON_F2_MAXP_SHA16 = "2568c57650fd61c4"
_CANON_F1_HMTX_SHA16 = "f3a867ade9a406be"
# Per unique-digit-cardinality F2.glyf ceilings (gated genuines max:
# card2=992, card3=1320, card4=1554, card5=1654). Headroom kept.
_F2_GLYF_FAT_BY_CARD = {
    1: 900,
    2: 1100,
    3: 1450,
    # card4 genuines max 1554 (сбп2); SEQ post-head-copy @1562 must not pass.
    4: 1554,
    # card5 genuines include 1654 (новые чеки); bank band documented to 1669.
    5: 1669,
    6: 1950,
    7: 2200,
}
_F2_GLYF_FAT_DEFAULT = 2400

# SEQ reassembly kit residue: identical unused simple outlines at F1 GIDs
# 113+227 (same glyf SHA across independent fakes). 0 hits on genuines.
_F1_KIT_ORPHAN_PAIR = frozenset({113, 227})
# Jasper may leave a single unmapped F2 spare (gid 306 on 2/48 SBP genuines)
# and rare F1 spares {35, 239} on the same pair. Any other unmapped nonempty
# outline is reassembly residue (0 FP on чеки/т банк gated genuines).
_F1_GENUINE_SPARES = frozenset({35, 239})
_F2_GENUINE_SPARES = frozenset({306})
# ≥2 unmapped nonempty F2 outlines is reassembly digit-pad, not bank subset.
_F2_ORPHAN_HARD_MIN = 2

_OBJ_HDR_RE = re.compile(rb"(\d+)\s+0\s+obj")
_PAGE_RE = re.compile(rb"/Type\s*/Page(?![sA-Za-z])")
_FONT_NAME_RE = re.compile(rb"/(F[123])\s+(\d+)\s+0\s+R")
_SUBJECT_MARKERS = (b"/reports/IB/Receipt", b"IB/Receipt")
_W_BLOCK_RE = re.compile(rb"/W\s*\[")


@dataclass
class V3Flag:
    code: str
    detail: str
    tier: str = "A"
    rule_id: str = ""
    group: str = ""


@dataclass
class V3Result:
    flags: list[V3Flag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Low-level PDF object graph
# ---------------------------------------------------------------------------

def _obj_spans(pdf: bytes) -> dict[int, bytes]:
    spans: dict[int, bytes] = {}
    for m in _OBJ_HDR_RE.finditer(pdf):
        num = int(m.group(1))
        end = pdf.find(b"endobj", m.start())
        if end > m.start():
            spans[num] = pdf[m.start():end]
    return spans


def _stream_payload(obj_blob: bytes) -> tuple[bytes, bytes]:
    """Return (raw_between_stream_endstream, decoded_after_filters).

    raw_len = bytes after skipping the EOL separator that follows the ``stream``
    keyword, up to ``endstream`` — trailing bytes before ``endstream`` are kept
    (not rstrip'd). decoded uses the zlib payload (= typically /Length bytes).
    """
    pos = obj_blob.find(b"stream")
    if pos < 0:
        return b"", b""
    cs = pos + 6
    if obj_blob[cs:cs + 2] == b"\r\n":
        cs += 2
    elif obj_blob[cs:cs + 1] in (b"\n", b"\r"):
        cs += 1
    es = obj_blob.find(b"endstream", cs)
    if es < 0:
        return b"", b""
    raw = obj_blob[cs:es]
    payload = raw.rstrip(b"\r\n")
    decoded = payload
    hdr = obj_blob[:pos]
    if b"/FlateDecode" in hdr or b"/Fl" in hdr:
        try:
            decoded = zlib.decompress(payload)
        except Exception:
            try:
                decoded = zlib.decompress(raw)
            except Exception:
                pass
    return raw, decoded


def _resolve_ref(blob: bytes, key: bytes) -> int | None:
    m = re.search(key + rb"\s+(\d+)\s+0\s+R", blob)
    return int(m.group(1)) if m else None


def _page_font_resources(spans: dict[int, bytes]) -> dict[str, int]:
    """Resolve Page → /Resources → /Font → /F1,/F2 via object graph (no fixed nums)."""
    page_blob = b""
    for blob in spans.values():
        if _PAGE_RE.search(blob) and b"/Parent" in blob:
            page_blob = blob
            break
    if not page_blob:
        for blob in spans.values():
            if _PAGE_RE.search(blob):
                page_blob = blob
                break
    if not page_blob:
        return {}

    fonts_blob = page_blob
    res_ref = _resolve_ref(page_blob, b"/Resources")
    if res_ref is not None and res_ref in spans:
        fonts_blob = spans[res_ref]
        # Resources may nest /Font <<...>> inline or as ref
        font_ref = _resolve_ref(fonts_blob, b"/Font")
        if font_ref is not None and font_ref in spans:
            fonts_blob = spans[font_ref]
    else:
        # Inline /Resources << ... /Font << /F1 n 0 R >> >>
        pass

    out: dict[str, int] = {}
    # Prefer /Font dictionary region
    font_dict = fonts_blob
    fm = re.search(rb"/Font\s*<<([^>]*)>>", fonts_blob, re.S)
    if fm:
        font_dict = fm.group(1)
    else:
        font_ref = _resolve_ref(fonts_blob, b"/Font")
        if font_ref is not None and font_ref in spans:
            font_dict = spans[font_ref]

    for m in _FONT_NAME_RE.finditer(font_dict):
        out[m.group(1).decode("ascii")] = int(m.group(2))

    # Fallback: whole PDF resource map (single-page IB receipts)
    if "F1" not in out or "F2" not in out:
        for m in _FONT_NAME_RE.finditer(b"".join(spans.values())):
            out.setdefault(m.group(1).decode("ascii"), int(m.group(2)))
    return out


@dataclass
class FontGraph:
    role: str
    type0_num: int = 0
    tounicode_num: int = 0
    descendant_num: int = 0
    descriptor_num: int = 0
    fontfile2_num: int = 0
    tounicode_raw: bytes = b""
    tounicode_decoded: bytes = b""
    fontfile2_raw: bytes = b""
    fontfile2_decoded: bytes = b""
    widths: dict[int, int] = field(default_factory=dict)
    tounicode: dict[int, str] = field(default_factory=dict)
    bfchar_count: int = 0
    bfrange_count: int = 0


def _parse_w_array(blob: bytes) -> dict[int, int]:
    widths: dict[int, int] = {}
    for m in _W_BLOCK_RE.finditer(blob):
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, min(len(blob), start + 20000)):
            ch = blob[i:i + 1]
            if ch == b"[":
                depth += 1
            elif ch == b"]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        arr = blob[start:end]
        for mm in re.finditer(rb"(\d+)\s*\[([^\]]*)\]", arr):
            c0 = int(mm.group(1))
            nums = [int(x) for x in re.findall(rb"-?\d+", mm.group(2))]
            for k, w in enumerate(nums):
                widths[c0 + k] = w
        arr2 = re.sub(rb"\d+\s*\[[^\]]*\]", b" ", arr)
        for mm in re.finditer(rb"(\d+)\s+(\d+)\s+(-?\d+)", arr2):
            c1, c2, w = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
            for cid in range(c1, c2 + 1):
                widths[cid] = w
    return widths


def _parse_tounicode(blob: bytes) -> tuple[dict[int, str], int, int]:
    """Full CMap parse. Counts = expanded CID→Unicode mappings per section type."""
    mapping: dict[int, str] = {}
    bfchar = 0
    bfrange = 0
    for block in re.finditer(rb"\d+\s+beginbfchar(.*?)endbfchar", blob or b"", re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block.group(1)):
            try:
                cid = int(src, 16)
                raw = bytes.fromhex(dst.decode())
                mapping[cid] = raw.decode("utf-16-be", "ignore")
                bfchar += 1
            except (ValueError, UnicodeError):
                pass
    for block in re.finditer(rb"\d+\s+beginbfrange(.*?)endbfrange", blob or b"", re.S):
        body = block.group(1)
        for lo, hi, base in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", body
        ):
            try:
                start, stop, unicode_base = int(lo, 16), int(hi, 16), int(base, 16)
                for offset, cid in enumerate(range(start, stop + 1)):
                    mapping[cid] = chr(unicode_base + offset)
                    bfrange += 1
            except (ValueError, OverflowError):
                pass
        for lo, hi, arr in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]", body
        ):
            try:
                start = int(lo, 16)
                values = re.findall(rb"<([0-9A-Fa-f]+)>", arr)
                for offset, hexv in enumerate(values):
                    cid = start + offset
                    raw = bytes.fromhex(hexv.decode())
                    mapping[cid] = raw.decode("utf-16-be", "ignore")
                    bfrange += 1
            except (ValueError, UnicodeError, OverflowError):
                pass
    return mapping, bfchar, bfrange


def _glyf_table_len(ttf: bytes) -> int:
    if not ttf or len(ttf) < 12:
        return 0
    try:
        nt = int.from_bytes(ttf[4:6], "big")
        for i in range(min(nt, 64)):
            o = 12 + i * 16
            if ttf[o:o + 4] == b"glyf":
                return int.from_bytes(ttf[o + 12:o + 16], "big")
    except Exception:
        pass
    return 0


def resolve_font_graph(pdf: bytes) -> dict[str, FontGraph]:
    """Resolve Page→Resources→Font→F1/F2/F3→…→FontFile2 via object graph.

    F1/F2 are Type0/CID; F3 may be a simple TrueType (ALSRubl) with
    FontDescriptor directly on the font object (no DescendantFonts).
    """
    spans = _obj_spans(pdf)
    res = _page_font_resources(spans)
    out: dict[str, FontGraph] = {}
    for role in ("F1", "F2", "F3"):
        num = res.get(role)
        if not num or num not in spans:
            continue
        g = FontGraph(role=role, type0_num=num)
        type0 = spans[num]
        tu_n = _resolve_ref(type0, b"/ToUnicode")
        desc_n = None
        dm = re.search(rb"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", type0)
        if dm:
            desc_n = int(dm.group(1))
            g.descendant_num = desc_n
        desc_blob = spans.get(desc_n, b"") if desc_n else b""
        if tu_n is None and desc_blob:
            tu_n = _resolve_ref(desc_blob, b"/ToUnicode")
        if tu_n is not None and tu_n in spans:
            g.tounicode_num = tu_n
            g.tounicode_raw, g.tounicode_decoded = _stream_payload(spans[tu_n])
            g.tounicode, g.bfchar_count, g.bfrange_count = _parse_tounicode(
                g.tounicode_decoded or g.tounicode_raw
            )
        widths = _parse_w_array(type0)
        if not widths and desc_blob:
            widths = _parse_w_array(desc_blob)
        g.widths = widths
        # CID: descriptor on descendant; simple TT (F3): descriptor on font itself.
        fd_n = _resolve_ref(desc_blob or type0, b"/FontDescriptor")
        if fd_n is None:
            fd_n = _resolve_ref(type0, b"/FontDescriptor")
        if fd_n is not None and fd_n in spans:
            g.descriptor_num = fd_n
            fd_blob = spans[fd_n]
            ff_n = _resolve_ref(fd_blob, b"/FontFile2")
            if ff_n is not None and ff_n in spans:
                g.fontfile2_num = ff_n
                g.fontfile2_raw, g.fontfile2_decoded = _stream_payload(spans[ff_n])
        out[role] = g
    return out


# ---------------------------------------------------------------------------
# Content-stream CID extraction (Identity-H aware)
# ---------------------------------------------------------------------------

def _decode_pdf_string_bytes(tok: bytes) -> bytes:
    """Decode PDF literal `(...)` including octal, \\nrtbf, \\(, \\), \\\\."""
    assert tok.startswith(b"(") and tok.endswith(b")")
    s = tok[1:-1]
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i:i + 1] == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt == b"n":
                out.append(10); i += 2; continue
            if nxt == b"r":
                out.append(13); i += 2; continue
            if nxt == b"t":
                out.append(9); i += 2; continue
            if nxt == b"b":
                out.append(8); i += 2; continue
            if nxt == b"f":
                out.append(12); i += 2; continue
            if nxt in b"()\\":
                out.extend(nxt); i += 2; continue
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


def _cids_from_operand(tok: bytes) -> list[int]:
    if tok.startswith(b"<") and tok.endswith(b">"):
        hexs = tok[1:-1].decode("ascii", "ignore")
        if len(hexs) % 4:
            hexs = hexs + "0" * (4 - len(hexs) % 4)
        return [int(hexs[i:i + 4], 16) for i in range(0, len(hexs), 4) if hexs[i:i + 4]]
    if tok.startswith(b"(") and tok.endswith(b")"):
        raw = _decode_pdf_string_bytes(tok)
        cids: list[int] = []
        for k in range(0, len(raw) - 1, 2):
            cids.append((raw[k] << 8) | raw[k + 1])
        return cids
    return []


_TF_RE = re.compile(rb"/(F\d+)\s+[\d.]+\s+Tf")
_TJ_OP_RE = re.compile(
    rb"(?:"
    rb"\((?:\\.|[^\\()])*\)"
    rb"|<(?:[0-9A-Fa-f]+)>"
    rb"|\[(?:[^\[\]]|\[[^\]]*\])*\]"
    rb")\s*TJ?",
    re.S,
)
_STR_IN_ARRAY_RE = re.compile(
    rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f]+>"
)


def extract_used_cids(pdf: bytes) -> dict[str, set[int]]:
    """Actual CIDs from Tj/TJ under current Tf (Identity-H, full escapes)."""
    used: dict[str, set[int]] = {}
    contents: list[bytes] = []
    primary = content_stream_bytes(pdf)
    if primary:
        contents.append(primary)
    else:
        for _raw, dec in find_streams(pdf):
            if dec and is_content_stream(dec):
                contents.append(dec)

    for content in contents:
        # Normalize CR/LF continuations inside strings is handled by operand decoder;
        # scan whole content (not line-bound) so multi-line TJ arrays work.
        current = ""
        pos = 0
        while pos < len(content):
            tf = _TF_RE.search(content, pos)
            tj = _TJ_OP_RE.search(content, pos)
            if tf and (not tj or tf.start() <= tj.start()):
                current = tf.group(1).decode("ascii")
                pos = tf.end()
                continue
            if not tj:
                break
            if current and current != "F3":
                operand = tj.group(0)
                # strip trailing Tj/TJ
                body = re.sub(rb"\s*TJ?\s*$", b"", operand)
                if body.startswith(b"["):
                    for tok in _STR_IN_ARRAY_RE.finditer(body):
                        for cid in _cids_from_operand(tok.group(0)):
                            used.setdefault(current, set()).add(cid)
                else:
                    for cid in _cids_from_operand(body.strip()):
                        used.setdefault(current, set()).add(cid)
            pos = tj.end()
    return used


# ---------------------------------------------------------------------------
# TTF helpers
# ---------------------------------------------------------------------------

def _cid_to_gid_identity(cid: int) -> int:
    return cid


def _ttf_advance_pdf_units(ttf: bytes, gid: int) -> int | None:
    if TTFont is None or not ttf:
        return None
    try:
        tt = TTFont(BytesIO(ttf))
        upem = int(tt["head"].unitsPerEm)
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return None
        name = order[gid]
        aw, _lsb = tt["hmtx"][name]
        return int(round(aw * 1000 / upem))
    except Exception:
        return None


def _composite_closure(ttf: bytes, seed_gids: set[int]) -> set[int]:
    if TTFont is None or not ttf:
        return set(seed_gids)
    try:
        tt = TTFont(BytesIO(ttf))
        glyf = tt["glyf"]
        order = tt.getGlyphOrder()
        name_of = {i: n for i, n in enumerate(order)}
        gid_of = {n: i for i, n in enumerate(order)}
        required = set(seed_gids)
        stack = list(seed_gids)
        while stack:
            gid = stack.pop()
            name = name_of.get(gid)
            if not name or name not in glyf:
                continue
            g = glyf[name]
            if getattr(g, "isComposite", lambda: False)():
                try:
                    g.expand(glyf)
                except Exception:
                    pass
                for comp in getattr(g, "components", []) or []:
                    cname = getattr(comp, "glyphName", None)
                    if not cname:
                        continue
                    cgid = gid_of.get(cname)
                    if cgid is not None and cgid not in required:
                        required.add(cgid)
                        stack.append(cgid)
        return required
    except Exception:
        return set(seed_gids)


def _nonempty_gids(ttf: bytes) -> set[int]:
    out: set[int] = set()
    if TTFont is None or not ttf:
        return out
    try:
        tt = TTFont(BytesIO(ttf))
        glyf = tt["glyf"]
        for gid, name in enumerate(tt.getGlyphOrder()):
            g = glyf[name]
            try:
                g.expand(glyf)
            except Exception:
                pass
            contours = int(getattr(g, "numberOfContours", 0) or 0)
            if contours != 0:
                out.add(gid)
            elif getattr(g, "isComposite", lambda: False)():
                out.add(gid)
        return out
    except Exception:
        return out


def _glyph_empty(ttf: bytes, gid: int) -> bool:
    if TTFont is None or not ttf:
        return True
    try:
        tt = TTFont(BytesIO(ttf))
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return True
        g = tt["glyf"][order[gid]]
        try:
            g.expand(tt["glyf"])
        except Exception:
            pass
        if getattr(g, "isComposite", lambda: False)():
            return False
        return int(getattr(g, "numberOfContours", 0) or 0) == 0
    except Exception:
        return True


def _loca_ok(ttf: bytes, gid: int) -> bool:
    tables = _ttf_tables(ttf)
    head = ttf[tables[b"head"][0]:tables[b"head"][0] + tables[b"head"][1]] if b"head" in tables else b""
    loca = ttf[tables[b"loca"][0]:tables[b"loca"][0] + tables[b"loca"][1]] if b"loca" in tables else b""
    maxp = ttf[tables[b"maxp"][0]:tables[b"maxp"][0] + tables[b"maxp"][1]] if b"maxp" in tables else b""
    if len(head) < 52 or len(maxp) < 6 or not loca:
        return False
    ng = struct.unpack(">H", maxp[4:6])[0]
    if gid < 0 or gid >= ng:
        return False
    fmt = struct.unpack(">H", head[50:52])[0]
    try:
        if fmt == 0:
            a = struct.unpack(">H", loca[gid * 2:gid * 2 + 2])[0] * 2
            b = struct.unpack(">H", loca[(gid + 1) * 2:(gid + 1) * 2 + 2])[0] * 2
        else:
            a = struct.unpack(">I", loca[gid * 4:gid * 4 + 4])[0]
            b = struct.unpack(">I", loca[(gid + 1) * 4:(gid + 1) * 4 + 4])[0]
        return a <= b
    except struct.error:
        return False


def _hmtx_exists(ttf: bytes, gid: int) -> bool:
    if TTFont is None or not ttf:
        return False
    try:
        tt = TTFont(BytesIO(ttf))
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return False
        _aw, _lsb = tt["hmtx"][order[gid]]
        return True
    except Exception:
        return False


def _maxp_num_glyphs(ttf: bytes) -> int:
    tables = _ttf_tables(ttf)
    if b"maxp" not in tables:
        return 0
    off, ln = tables[b"maxp"]
    maxp = ttf[off:off + ln]
    if len(maxp) < 6:
        return 0
    return struct.unpack(">H", maxp[4:6])[0]


# ---------------------------------------------------------------------------
# Profile gate
# ---------------------------------------------------------------------------

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


def _channel_and_meta(
    pdf: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> tuple[str, str, str, str, bool, bool, bool, bool]:
    if not producer and not creator:
        producer, creator = _meta(pdf)
    if not text:
        text = _pdf_text(pdf)
    channel = detect_receipt_channel(text)
    # Prefer explicit SBP markers used by v6 stages
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
    creator_ok = "jasperreports" in (creator or "").lower()
    return (
        channel, text, producer, creator,
        confirmed, subject_ok, producer_ok, creator_ok,
    )


def profile_gate_confirmed_jasper(
    pdf: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Confirmed Jasper/OpenPDF IB/Receipt — any channel (card/phone/SBP).

    Used by used≡ToUnicode≡/W bijection + cmap/W minimality + exact closure.
    Those invariants hold on genuines across channels (n=128, 0 FP); SBP-only
    gating let SEQ card/phone shells keep donor ToUnicode leftovers.
    """
    (
        channel, _text, producer, creator,
        confirmed, subject_ok, producer_ok, creator_ok,
    ) = _channel_and_meta(pdf, text=text, producer=producer, creator=creator)
    ok = bool(
        confirmed
        and subject_ok
        and producer_ok
        and creator_ok
    )
    return ok, {
        "profile_gate": ok,
        "gate": "confirmed_jasper_any_channel",
        "confirmed_tbank_profile": confirmed,
        "channel": channel,
        "subject_ok": subject_ok,
        "producer_ok": producer_ok,
        "creator_ok": creator_ok,
        "producer": producer,
        "creator": creator,
        "profile_id": PROFILE_ID,
    }


def profile_gate(
    pdf: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> tuple[bool, dict[str, Any]]:
    """SBP-only gate for family-v3 / maxp / orphan-residue (card FP otherwise)."""
    (
        channel, _text, producer, creator,
        confirmed, subject_ok, producer_ok, creator_ok,
    ) = _channel_and_meta(pdf, text=text, producer=producer, creator=creator)
    ok = bool(
        confirmed
        and channel == CHANNEL_SBP
        and subject_ok
        and producer_ok
        and creator_ok
    )
    return ok, {
        "profile_gate": ok,
        "gate": "confirmed_jasper_sbp",
        "confirmed_tbank_profile": confirmed,
        "channel": channel,
        "subject_ok": subject_ok,
        "producer_ok": producer_ok,
        "creator_ok": creator_ok,
        "producer": producer,
        "creator": creator,
        "profile_id": PROFILE_ID,
    }


# ---------------------------------------------------------------------------
# Signature metrics + family v3
# ---------------------------------------------------------------------------

_TOUNICODE_PAIR_RE = re.compile(
    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>"
)
_TOUNICODE_RANGE_RE = re.compile(
    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>"
)


def _f2_unique_digit_cardinality(f2: FontGraph | None) -> int:
    """Count unique ASCII digit codepoints mapped in F2 ToUnicode."""
    if f2 is None:
        return 0
    tu = (f2.tounicode_decoded or b"").decode("latin1", "replace")
    digits: set[int] = set()
    for m in _TOUNICODE_PAIR_RE.finditer(tu):
        uni = int(m.group(2), 16)
        if 0x30 <= uni <= 0x39:
            digits.add(uni)
    for m in _TOUNICODE_RANGE_RE.finditer(tu):
        start = int(m.group(1), 16)
        end = int(m.group(2), 16)
        uni0 = int(m.group(3), 16)
        for cid in range(start, end + 1):
            uni = uni0 + (cid - start)
            if 0x30 <= uni <= 0x39:
                digits.add(uni)
    return len(digits)


def _f2_glyf_expanded(f2_glyf: int, digit_card: int) -> bool:
    """True for synthetic-fat F2.glyf vs digit vocabulary.

    Gated genuines: card2≤992, card3≤1320, card4≤1554, card5≤1654.
    SEQ after copying F2.head still ships Medium glyf far above those bands
    (e.g. card3 @1560–1630). Thresholds keep headroom; 0 FP on n=56.
    """
    return f2_glyf > _F2_GLYF_FAT_BY_CARD.get(digit_card, _F2_GLYF_FAT_DEFAULT)


def _font_stream_metrics(graphs: dict[str, FontGraph]) -> dict[str, Any]:
    f1 = graphs.get("F1")
    f2 = graphs.get("F2")
    f1_glyf = _glyf_table_len(f1.fontfile2_decoded) if f1 else 0
    f2_glyf = _glyf_table_len(f2.fontfile2_decoded) if f2 else 0
    f1_bfchar = f1.bfchar_count if f1 else 0
    f2_bfrange = f2.bfrange_count if f2 else 0
    f1_raw = len(f1.fontfile2_raw) if f1 else 0
    f1_dec = len(f1.fontfile2_decoded) if f1 else 0
    f2_tu_raw = len(f2.tounicode_raw) if f2 else 0
    f2_tu_dec = len(f2.tounicode_decoded) if f2 else 0
    f2_digit_card = _f2_unique_digit_cardinality(f2)
    f2_expanded = _f2_glyf_expanded(f2_glyf, f2_digit_card)

    # F2.glyf bank band for SBP Medium: corpus ~812…1654 (сбп8=1636 with
    # 5 unique amount digits). [1550, 1850] is legitimate variability — do NOT
    # treat as compact or expanded reassembly. Expanded is digit-card aware.
    _F2_GLYF_COMPACT_MAX = 1549  # exclusive of bank «fat» band starting 1550
    font_signature = (
        f2_bfrange >= 10
        and (
            f1_glyf <= 12783
            or f2_expanded
            or (f2_glyf <= _F2_GLYF_COMPACT_MAX and f1_bfchar <= 105)
        )
    )
    stream_signature = (
        f2_tu_dec > 495
        and (
            f1_raw <= 9205
            or f1_dec > 17198
            or (f1_dec <= 17120 and f2_tu_raw > 279)
        )
    )
    return {
        "f1_glyf_len": f1_glyf,
        "f2_glyf_len": f2_glyf,
        "f2_unique_digit_card": f2_digit_card,
        "f1_tounicode_bfchar_count": f1_bfchar,
        "f2_tounicode_bfrange_count": f2_bfrange,
        "f1_fontfile2_raw_len": f1_raw,
        "f1_fontfile2_decoded_len": f1_dec,
        "f2_tounicode_raw_len": f2_tu_raw,
        "f2_tounicode_decoded_len": f2_tu_dec,
        "font_signature": font_signature,
        "stream_signature": stream_signature,
        "TBANK_F2_DENSE_TOUNICODE_SUBSET": f2_bfrange >= 10,
        "TBANK_F1_GLYF_COMPACT_REASSEMBLY": f1_glyf <= 12783,
        "TBANK_F2_GLYF_EXPANDED_REASSEMBLY": f2_expanded,
        "TBANK_F1_TOUNICODE_CARDINALITY_PROFILE": f1_bfchar <= 105,
        "TBANK_F1_FONTFILE2_STREAM_LATTICE": f1_raw <= 9205 or f1_dec > 17198,
        "TBANK_F2_TOUNICODE_STREAM_LATTICE": f2_tu_dec > 495,
        "TBANK_FONT_CMAP_SERIALIZATION_CROSS_LAYER": stream_signature,
    }


def check_tbank_reassembly_family_v3(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
) -> V3Result:
    out = V3Result()
    gate_ok, gate_stats = profile_gate(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    metrics = _font_stream_metrics(graphs)
    out.stats.update(metrics)
    out.stats["font_obj_nums"] = {
        role: {
            "type0": g.type0_num,
            "tounicode": g.tounicode_num,
            "descendant": g.descendant_num,
            "descriptor": g.descriptor_num,
            "fontfile2": g.fontfile2_num,
        }
        for role, g in graphs.items()
    }

    if metrics["font_signature"] and metrics["stream_signature"]:
        detail = (
            "T-Bank SBP Jasper/OpenPDF shell contains the confirmed "
            "F1/F2 reconstructed-subset serialization family v3: "
            f"F1.glyf={metrics['f1_glyf_len']}, "
            f"F2.glyf={metrics['f2_glyf_len']}, "
            f"F1.ToUnicode={metrics['f1_tounicode_bfchar_count']}, "
            f"F2.ToUnicode={metrics['f2_tounicode_bfrange_count']}, "
            f"F1.FontFile2.raw={metrics['f1_fontfile2_raw_len']}, "
            f"F1.FontFile2.decoded={metrics['f1_fontfile2_decoded_len']}, "
            f"F2.ToUnicode.raw={metrics['f2_tounicode_raw_len']}, "
            f"F2.ToUnicode.decoded={metrics['f2_tounicode_decoded_len']}"
        )
        out.flags.append(V3Flag(
            code=CODE_FAMILY,
            detail=detail,
            tier="KNOWN",
            rule_id=RULE_FAMILY,
            group="known_reassembly_family",
        ))
    return out


# ---------------------------------------------------------------------------
# Minimality / bijection / closure
# ---------------------------------------------------------------------------

def check_tbank_subset_cmap_minimality(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
    used: dict[str, set[int]] | None = None,
) -> V3Result:
    out = V3Result()
    gate_ok, gate_stats = profile_gate_confirmed_jasper(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    used = used if used is not None else extract_used_cids(pdf_bytes)
    out.stats["used_cids"] = {k: sorted(v) for k, v in used.items()}

    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g:
            continue
        mapped = set(g.tounicode)
        used_cids = used.get(role, set())
        extra = sorted(mapped - used_cids)
        out.stats[f"{role}_extra_mapped"] = extra
        out.stats[f"{role}_mapped_n"] = len(mapped)
        out.stats[f"{role}_used_n"] = len(used_cids)
        if extra:
            out.flags.append(V3Flag(
                code=CODE_CMAP,
                detail=(
                    f"{role} ToUnicode maps unused CIDs {extra} "
                    f"(used={len(used_cids)}, mapped={len(mapped)}) — "
                    "Jasper/OpenPDF subset ToUnicode must be exact-minimal"
                ),
                tier="A",
                rule_id=RULE_CMAP,
                group="font_cmap_glyph",
            ))
    return out


def check_tbank_w_array_minimality(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
    used: dict[str, set[int]] | None = None,
) -> V3Result:
    out = V3Result()
    gate_ok, gate_stats = profile_gate_confirmed_jasper(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    used = used if used is not None else extract_used_cids(pdf_bytes)

    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g:
            continue
        used_cids = used.get(role, set())
        mapped = set(g.tounicode)
        w_cids = set(g.widths)
        extra_w = sorted(w_cids - used_cids)
        out.stats[f"{role}_extra_w"] = extra_w
        if extra_w or w_cids != mapped or w_cids != used_cids:
            # HARD on any CID in /W absent from real text operators
            if extra_w:
                out.flags.append(V3Flag(
                    code=CODE_W,
                    detail=(
                        f"{role} /W contains CIDs not used in content: {extra_w} "
                        f"(used={sorted(used_cids)[:12]}…)"
                    ),
                    tier="A",
                    rule_id=RULE_W,
                    group="font_cmap_glyph",
                ))

        ttf = g.fontfile2_decoded
        mismatches: list[str] = []
        for cid in sorted(used_cids & w_cids):
            pdf_w = g.widths.get(cid)
            if pdf_w is None:
                continue
            gid = _cid_to_gid_identity(cid)
            adv = _ttf_advance_pdf_units(ttf, gid)
            if adv is not None and int(pdf_w) != int(adv):
                mismatches.append(f"CID {cid}: /W={pdf_w} ttf={adv}")
        if mismatches:
            out.flags.append(V3Flag(
                code=CODE_W_ADV,
                detail=(
                    f"{role} /W ≠ round(ttf_aw*1000/upem): "
                    + "; ".join(mismatches[:8])
                ),
                tier="A",
                rule_id=RULE_W_ADV,
                group="font_cmap_glyph",
            ))
            out.stats[f"{role}_w_ttf_mismatches"] = mismatches
    return out


def check_tbank_cid_serialization_bijection(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
    used: dict[str, set[int]] | None = None,
) -> V3Result:
    out = V3Result()
    gate_ok, gate_stats = profile_gate_confirmed_jasper(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    used = used if used is not None else extract_used_cids(pdf_bytes)

    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g:
            continue
        used_cids = used.get(role, set())
        tu_cids = set(g.tounicode)
        w_cids = set(g.widths)
        if not (used_cids == tu_cids == w_cids):
            out.flags.append(V3Flag(
                code=CODE_BIJ,
                detail=(
                    f"{role} used/ToUnicode/W not bijective: "
                    f"|used|={len(used_cids)} |tu|={len(tu_cids)} |W|={len(w_cids)}; "
                    f"extra_tu={sorted(tu_cids - used_cids)[:12]}; "
                    f"extra_w={sorted(w_cids - used_cids)[:12]}; "
                    f"missing_tu={sorted(used_cids - tu_cids)[:12]}"
                ),
                tier="A",
                rule_id=RULE_BIJ,
                group="font_cmap_glyph",
            ))

        ttf = g.fontfile2_decoded
        ng = _maxp_num_glyphs(ttf)
        problems: list[str] = []
        for cid in sorted(used_cids):
            uni = g.tounicode.get(cid, "")
            gid = _cid_to_gid_identity(cid)
            if ng and gid >= ng:
                problems.append(f"CID {cid} gid {gid} >= numGlyphs {ng}")
                continue
            if not _loca_ok(ttf, gid):
                problems.append(f"CID {cid} loca broken")
            if not _hmtx_exists(ttf, gid):
                problems.append(f"CID {cid} missing hmtx")
            empty = _glyph_empty(ttf, gid)
            if empty and uni != " ":
                problems.append(f"CID {cid} empty glyf for {uni!r}")
        if problems:
            out.flags.append(V3Flag(
                code=CODE_BIJ,
                detail=f"{role} glyph chain violations: " + "; ".join(problems[:10]),
                tier="A",
                rule_id=RULE_BIJ,
                group="font_cmap_glyph",
            ))
            out.stats[f"{role}_bijection_problems"] = problems
    return out


def check_tbank_font_subset_exact_closure(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
    used: dict[str, set[int]] | None = None,
) -> V3Result:
    out = V3Result()
    gate_ok, gate_stats = profile_gate_confirmed_jasper(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    used = used if used is not None else extract_used_cids(pdf_bytes)

    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g or not g.fontfile2_decoded:
            continue
        ttf = g.fontfile2_decoded
        used_cids = used.get(role, set())
        # Space CID may have empty glyf
        space_gids = {
            _cid_to_gid_identity(cid)
            for cid, ch in g.tounicode.items()
            if ch == " "
        }
        direct = {_cid_to_gid_identity(c) for c in used_cids}
        required = _composite_closure(ttf, direct)
        expected = required | {0}
        actual = _nonempty_gids(ttf)
        # Allow empty space glyph: remove space gids from "must be nonempty"
        must_nonempty = required - space_gids
        unexpected_all = sorted(actual - expected)
        missing = sorted(must_nonempty - actual)
        # Jasper originals ship a few unmapped spare outlines in FontFile2.
        # HARD only when an unexpected nonempty GID is also serialized into
        # ToUnicode or /W (reconstructed subset residue), or when required
        # glyphs are missing.
        serialized = set(g.tounicode) | set(g.widths)
        unexpected = sorted(set(unexpected_all) & serialized)
        out.stats[f"{role}_required_gids_n"] = len(required)
        out.stats[f"{role}_nonempty_gids_n"] = len(actual)
        out.stats[f"{role}_unexpected_nonempty_all"] = unexpected_all
        out.stats[f"{role}_unexpected_nonempty"] = unexpected
        out.stats[f"{role}_missing_required"] = missing
        if unexpected or missing:
            out.flags.append(V3Flag(
                code=CODE_CLOSURE,
                detail=(
                    f"{role} FontFile2 subset closure broken: "
                    f"unexpected_nonempty={unexpected[:16]} "
                    f"missing_required={missing[:16]}"
                ),
                tier="A",
                rule_id=RULE_CLOSURE,
                group="font_cmap_glyph",
            ))
    return out


def check_tbank_subset_orphan_residue(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
    used: dict[str, set[int]] | None = None,
) -> V3Result:
    """HARD on unmapped nonempty FontFile2 residue that genuines do not ship.

    Closure HARD only fires when spare outlines are also serialized into
    ToUnicode|/W. SEQ rebuilders often pad glyf with unused digit/letter
    outlines that stay out of cmap — competitors catch that; we previously
    ignored it. Refined gate (0 FP on чеки/т банк gated genuines):

    - F1/F2: any unmapped nonempty outside the tiny genuine spare sets
      F1∈{35,239}, F2∈{306} (сбп2/8 only)
    - F2: ≥2 unmapped nonempty (digit pad)
    - F1: kit orphan pair {113, 227}
    """
    out = V3Result()
    gate_ok, gate_stats = profile_gate(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    used = used if used is not None else extract_used_cids(pdf_bytes)

    orphans: dict[str, list[int]] = {}
    for role in ("F1", "F2"):
        g = graphs.get(role)
        if not g or not g.fontfile2_decoded:
            continue
        ttf = g.fontfile2_decoded
        seeds = set(g.tounicode) | used.get(role, set())
        clo = _composite_closure(ttf, seeds)
        unexpected = sorted(_nonempty_gids(ttf) - clo - {0})
        orphans[role] = unexpected
        out.stats[f"{role}_orphan_nonempty"] = unexpected

    f1_orph = set(orphans.get("F1", []))
    f2_orph = set(orphans.get("F2", []))
    f1_bad = sorted(f1_orph - _F1_GENUINE_SPARES)
    f2_bad = sorted(f2_orph - _F2_GENUINE_SPARES)
    f1_kit = _F1_KIT_ORPHAN_PAIR.issubset(f1_orph)
    f2_pad = len(f2_orph) >= _F2_ORPHAN_HARD_MIN
    out.stats["f1_kit_orphan_pair"] = f1_kit
    out.stats["f2_orphan_pad"] = f2_pad
    out.stats["f1_orphan_non_genuine"] = f1_bad
    out.stats["f2_orphan_non_genuine"] = f2_bad
    if not (f1_kit or f2_pad or f1_bad or f2_bad):
        return out

    parts: list[str] = []
    if f1_kit:
        parts.append(
            f"F1 kit orphan pair {sorted(_F1_KIT_ORPHAN_PAIR)} "
            f"present in unmapped nonempty={sorted(f1_orph)[:16]}"
        )
    if f1_bad:
        parts.append(
            f"F1 non-genuine unmapped nonempty={f1_bad[:16]} "
            f"(allowed spares={sorted(_F1_GENUINE_SPARES)})"
        )
    if f2_pad:
        parts.append(
            f"F2 unmapped nonempty orphans={sorted(f2_orph)[:16]} "
            f"(n={len(f2_orph)}≥{_F2_ORPHAN_HARD_MIN})"
        )
    elif f2_bad:
        parts.append(
            f"F2 non-genuine unmapped nonempty={f2_bad[:16]} "
            f"(allowed spare={sorted(_F2_GENUINE_SPARES)})"
        )
    out.flags.append(V3Flag(
        code=CODE_ORPHAN_RESIDUE,
        detail=(
            "FontFile2 reassembly residue (unmapped nonempty outside "
            "used∪ToUnicode closure): " + "; ".join(parts)
        ),
        tier="A",
        rule_id=RULE_ORPHAN_RESIDUE,
        group="font_cmap_glyph",
    ))
    return out


def _f1_glyf_extrema(ttf: bytes) -> tuple[int, int, int] | None:
    """Return (maxPoints, maxContours, maxComponentElements) from glyf/loca."""
    try:
        from detector.tbank_v6.f1_subset_shape import _loca_offsets, _parse_sfnt_tables
    except Exception:
        return None
    tables = _parse_sfnt_tables(ttf)
    loca = _loca_offsets(tables)
    glyf = tables.get(b"glyf")
    if not loca or not glyf:
        return None
    offsets, _ng = loca
    max_pts = 0
    max_cont = 0
    max_comp = 0
    for gid in range(len(offsets) - 1):
        a, b = offsets[gid], offsets[gid + 1]
        if b <= a or b > len(glyf):
            continue
        data = glyf[a:b]
        if len(data) < 2:
            continue
        ncont = struct.unpack(">h", data[:2])[0]
        if ncont >= 0:
            if ncont > max_cont:
                max_cont = ncont
            if ncont > 0 and len(data) >= 10 + 2 * ncont:
                end_pts = struct.unpack(">" + "H" * ncont, data[10:10 + 2 * ncont])
                pts = end_pts[-1] + 1
                if pts > max_pts:
                    max_pts = pts
        else:
            i = 10
            comps = 0
            while i + 4 <= len(data):
                flags = struct.unpack(">H", data[i:i + 2])[0]
                comps += 1
                i += 4
                if flags & 0x0001:
                    i += 4
                else:
                    i += 2
                if flags & 0x0008:
                    i += 2
                elif flags & 0x0040:
                    i += 4
                elif flags & 0x0080:
                    i += 8
                if not (flags & 0x0020):
                    break
            if comps > max_comp:
                max_comp = comps
    return max_pts, max_cont, max_comp


def check_tbank_f1_maxp_recomputed_to_subset(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    graphs: dict[str, FontGraph] | None = None,
) -> V3Result:
    """HARD when F1 maxp extrema were recomputed to the embedded subset glyf.

    Native Jasper/OpenPDF keeps the full TinkoffSans maxp envelope
    (typically maxPoints=100, maxContours=7, maxComponentElements=3) even
    after CID subsetting — actual glyf extrema stay strictly below those
    fields (0 hits equal on чеки/т банк gated genuines). SEQ rebuilders
    rewrite maxp to exact subset extrema (often 85/4/1).
    """
    out = V3Result()
    gate_ok, gate_stats = profile_gate(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = graphs or resolve_font_graph(pdf_bytes)
    g1 = graphs.get("F1")
    if not g1 or not g1.fontfile2_decoded:
        out.stats["skipped"] = "no_f1"
        return out
    ttf = g1.fontfile2_decoded
    try:
        from detector.tbank_v6.f1_subset_shape import _parse_sfnt_tables
        maxp = _parse_sfnt_tables(ttf).get(b"maxp")
    except Exception:
        maxp = None
    if not maxp or len(maxp) < 32:
        out.stats["skipped"] = "maxp_parse"
        return out
    actual = _f1_glyf_extrema(ttf)
    if not actual:
        out.stats["skipped"] = "glyf_extrema"
        return out
    mp = struct.unpack(">H", maxp[6:8])[0]
    mc = struct.unpack(">H", maxp[8:10])[0]
    mcomp = struct.unpack(">H", maxp[28:30])[0]
    mcp = struct.unpack(">H", maxp[10:12])[0]  # maxCompositePoints
    mcc = struct.unpack(">H", maxp[12:14])[0]  # maxCompositeContours
    ap, ac, acomp = actual
    out.stats["f1_maxp_extrema"] = (mp, mc, mcomp)
    out.stats["f1_glyf_extrema"] = (ap, ac, acomp)
    out.stats["f1_maxp_composite"] = (mcp, mcc)
    equal = mp == ap and mc == ac and mcomp == acomp
    out.stats["f1_maxp_recomputed"] = equal
    composite_ok = (
        mcp == _CANON_MAX_COMPOSITE_POINTS
        and mcc == _CANON_MAX_COMPOSITE_CONTOURS
    )
    out.stats["f1_maxp_composite_ok"] = composite_ok
    if equal:
        out.flags.append(V3Flag(
            code=CODE_MAXP_RECOMPUTED,
            detail=(
                f"F1 maxp extrema recomputed to subset glyf: "
                f"maxPoints/maxContours/maxComponentElements="
                f"{mp}/{mc}/{mcomp} == actual glyf {ap}/{ac}/{acomp} — "
                f"Jasper keeps full-font maxp envelope, not exact subset"
            ),
            tier="A",
            rule_id=RULE_MAXP_RECOMPUTED,
            group="font_cmap_glyph",
        ))
    if not composite_ok:
        out.flags.append(V3Flag(
            code=CODE_MAXP_COMPOSITE,
            detail=(
                f"F1 maxp composite envelope "
                f"maxCompositePoints/maxCompositeContours={mcp}/{mcc} "
                f"≠ Jasper full-font {_CANON_MAX_COMPOSITE_POINTS}/"
                f"{_CANON_MAX_COMPOSITE_CONTOURS} — SEQ partial maxp rewrite "
                f"(keeps maxPoints={mp} but shrinks composite stats)"
            ),
            tier="A",
            rule_id=RULE_MAXP_COMPOSITE,
            group="font_cmap_glyph",
        ))
    try:
        from detector.tbank_v6.f1_subset_shape import _parse_sfnt_tables as _sfnt
        hhea = _sfnt(ttf).get(b"hhea") or b""
    except Exception:
        hhea = b""
    hhea_sha16 = hashlib.sha256(hhea).hexdigest()[:16] if hhea else ""
    out.stats["f1_hhea_sha16"] = hhea_sha16
    out.stats["f1_hhea_ok"] = hhea_sha16 == _CANON_F1_HHEA_SHA16
    if hhea and hhea_sha16 != _CANON_F1_HHEA_SHA16:
        out.flags.append(V3Flag(
            code=CODE_HHEA_ENVELOPE,
            detail=(
                f"F1 hhea sha16={hhea_sha16} ≠ Jasper full-font "
                f"{_CANON_F1_HHEA_SHA16} — SEQ rewrote hhea while keeping "
                f"shared hmtx/maxp shell (n=56 genuines share one hhea blob)"
            ),
            tier="A",
            rule_id=RULE_HHEA_ENVELOPE,
            group="font_cmap_glyph",
        ))
    g2 = graphs.get("F2")
    f2_head = b""
    if g2 and g2.fontfile2_decoded:
        try:
            from detector.tbank_v6.f1_subset_shape import _parse_sfnt_tables as _sfnt2
            f2_head = _sfnt2(g2.fontfile2_decoded).get(b"head") or b""
        except Exception:
            f2_head = b""
    f2_head_sha16 = hashlib.sha256(f2_head).hexdigest()[:16] if f2_head else ""
    out.stats["f2_head_sha16"] = f2_head_sha16
    out.stats["f2_head_ok"] = f2_head_sha16 == _CANON_F2_HEAD_SHA16
    if f2_head and f2_head_sha16 != _CANON_F2_HEAD_SHA16:
        out.flags.append(V3Flag(
            code=CODE_F2_HEAD_ENVELOPE,
            detail=(
                f"F2 head sha16={f2_head_sha16} ≠ Jasper Medium "
                f"{_CANON_F2_HEAD_SHA16} — SEQ rewrote head checkSumAdjustment "
                f"after F2.glyf reassembly (n=56 genuines share one head blob)"
            ),
            tier="A",
            rule_id=RULE_F2_HEAD_ENVELOPE,
            group="font_cmap_glyph",
        ))
    # F1 hmtx envelope (full TinkoffSans advances) — identical on genuines.
    try:
        from detector.tbank_v6.f1_subset_shape import _parse_sfnt_tables as _sfnt3
        f1_hmtx = _sfnt3(ttf).get(b"hmtx") or b""
    except Exception:
        f1_hmtx = b""
    f1_hmtx_sha16 = hashlib.sha256(f1_hmtx).hexdigest()[:16] if f1_hmtx else ""
    out.stats["f1_hmtx_sha16"] = f1_hmtx_sha16
    out.stats["f1_hmtx_ok"] = f1_hmtx_sha16 == _CANON_F1_HMTX_SHA16
    if f1_hmtx and f1_hmtx_sha16 != _CANON_F1_HMTX_SHA16:
        out.flags.append(V3Flag(
            code=CODE_F1_HMTX_ENVELOPE,
            detail=(
                f"F1 hmtx sha16={f1_hmtx_sha16} ≠ Jasper full-font "
                f"{_CANON_F1_HMTX_SHA16} — SEQ rewrote advances while keeping "
                f"shared head/hhea/maxp shell (n=56 genuines share one hmtx)"
            ),
            tier="A",
            rule_id=RULE_F1_HMTX_ENVELOPE,
            group="font_cmap_glyph",
        ))
    # F2 maxp / glyf↔loca pad / digit-card fat (post F2.head-copy SEQ).
    f2_maxp = b""
    f2_glyf_len = 0
    f2_pad = 0
    if g2 and g2.fontfile2_decoded:
        try:
            from detector.tbank_v6.f1_subset_shape import (
                _loca_offsets as _loca2,
                _parse_sfnt_tables as _sfnt4,
            )
            tb2 = _sfnt4(g2.fontfile2_decoded)
            f2_maxp = tb2.get(b"maxp") or b""
            glyf2 = tb2.get(b"glyf") or b""
            f2_glyf_len = len(glyf2)
            loc2 = _loca2(tb2)
            if loc2 and glyf2:
                f2_pad = f2_glyf_len - loc2[0][-1]
        except Exception:
            pass
    f2_maxp_sha16 = hashlib.sha256(f2_maxp).hexdigest()[:16] if f2_maxp else ""
    out.stats["f2_maxp_sha16"] = f2_maxp_sha16
    out.stats["f2_maxp_ok"] = f2_maxp_sha16 == _CANON_F2_MAXP_SHA16
    out.stats["f2_glyf_pad"] = f2_pad
    if f2_maxp and f2_maxp_sha16 != _CANON_F2_MAXP_SHA16:
        out.flags.append(V3Flag(
            code=CODE_F2_MAXP_ENVELOPE,
            detail=(
                f"F2 maxp sha16={f2_maxp_sha16} ≠ Jasper Medium "
                f"{_CANON_F2_MAXP_SHA16} — SEQ rewrote maxp extrema/composite "
                f"after F2.glyf reassembly (n=56 genuines share one maxp blob)"
            ),
            tier="A",
            rule_id=RULE_F2_MAXP_ENVELOPE,
            group="font_cmap_glyph",
        ))
    if f2_pad > 0:
        out.flags.append(V3Flag(
            code=CODE_F2_GLYF_PAD,
            detail=(
                f"F2 glyf has {f2_pad} bytes past loca end "
                f"(glyf_len={f2_glyf_len}) — reassembly trailing residue; "
                f"all gated genuines have pad=0"
            ),
            tier="A",
            rule_id=RULE_F2_GLYF_PAD,
            group="font_cmap_glyph",
        ))
    digit_card = _f2_unique_digit_cardinality(g2) if g2 else 0
    fat_thr = _F2_GLYF_FAT_BY_CARD.get(digit_card, _F2_GLYF_FAT_DEFAULT)
    out.stats["f2_unique_digit_card"] = digit_card
    out.stats["f2_glyf_len"] = f2_glyf_len
    out.stats["f2_glyf_fat_thr"] = fat_thr
    if f2_glyf_len > fat_thr:
        out.flags.append(V3Flag(
            code=CODE_F2_DIGIT_FAT,
            detail=(
                f"F2.glyf={f2_glyf_len} > digit-card ceiling {fat_thr} "
                f"(unique digits={digit_card}) — synthetic Medium fat after "
                f"digit-pad reassembly; gated genuines stay under ceiling"
            ),
            tier="A",
            rule_id=RULE_F2_DIGIT_FAT,
            group="font_cmap_glyph",
        ))
    # F1 glyf_len → shape envelope (singleton lengths only).
    try:
        from detector.tbank_v6.f1_subset_shape import _f1_shape as _shape_f1
        sh = _shape_f1(pdf_bytes)
    except Exception:
        sh = None
    if sh:
        glen = int(sh.get("glyf_len") or 0)
        got = (
            int(sh.get("composite_n") or 0),
            int(sh.get("nonempty_n") or 0),
            int(sh.get("simple_n") or 0),
            int(sh.get("cmap_n") or 0),
        )
        allowed = _F1_GLYF_SHAPES_BY_LEN.get(glen)
        out.stats["f1_glyf_len"] = glen
        out.stats["f1_shape"] = got
        out.stats["f1_shape_allowed"] = sorted(allowed) if allowed else None
        if allowed is not None and got not in allowed:
            out.flags.append(V3Flag(
                code=CODE_F1_GLYF_SHAPE,
                detail=(
                    f"F1 glyf_len={glen} shape composite/nonempty/simple/cmap="
                    f"{got} ∉ Jasper allowed {sorted(allowed)} — SEQ kept "
                    f"donor glyf byte-length but swapped glyph inventory"
                ),
                tier="A",
                rule_id=RULE_F1_GLYF_SHAPE,
                group="font_cmap_glyph",
            ))
        # Anonymous nonempty glyph-size multiset (survives same shape counts).
        size_allowed = _F1_GLYF_SIZE_HASH_BY_LEN.get(glen)
        if size_allowed is not None and g1 and g1.fontfile2_decoded:
            try:
                from detector.tbank_v6.f1_subset_shape import (
                    _loca_offsets as _loca_sz,
                    _parse_sfnt_tables as _sfnt_sz,
                )
                tb_sz = _sfnt_sz(g1.fontfile2_decoded)
                loc_sz = _loca_sz(tb_sz)
                if loc_sz:
                    offs_sz, _ = loc_sz
                    sizes = tuple(
                        sorted(
                            offs_sz[gid + 1] - offs_sz[gid]
                            for gid in _nonempty_gids(g1.fontfile2_decoded)
                        )
                    )
                    size_sha16 = hashlib.sha256(str(sizes).encode()).hexdigest()[:16]
                    out.stats["f1_glyf_size_sha16"] = size_sha16
                    out.stats["f1_glyf_size_ok"] = size_sha16 in size_allowed
                    if size_sha16 not in size_allowed:
                        out.flags.append(V3Flag(
                            code=CODE_F1_GLYF_SIZES,
                            detail=(
                                f"F1 glyf_len={glen} nonempty glyph-size "
                                f"multiset sha16={size_sha16} ∉ Jasper allowed "
                                f"{sorted(size_allowed)} — SEQ kept glyf byte-"
                                f"length/shape counts but swapped outline sizes"
                            ),
                            tier="A",
                            rule_id=RULE_F1_GLYF_SIZES,
                            group="font_cmap_glyph",
                        ))
            except Exception:
                pass
    return out


def run_tbank_reassembly_family_v3_stack(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> V3Result:
    """Run bijection → cmap → W → closure → family-v3 under one shared graph.

    Entry gate is confirmed Jasper any-channel so card/phone SEQ shells that
    keep donor ToUnicode leftovers are scored. SBP-only checks (family-v3 /
    maxp / orphan-residue) still self-gate via profile_gate().
    """
    out = V3Result()
    gate_ok, gate_stats = profile_gate_confirmed_jasper(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate_stats)
    if not gate_ok:
        out.stats["skipped"] = "profile_gate"
        return out

    graphs = resolve_font_graph(pdf_bytes)
    used = extract_used_cids(pdf_bytes)
    out.stats["used_cids"] = {k: sorted(v) for k, v in used.items()}

    parts = [
        check_tbank_cid_serialization_bijection(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs, used=used,
        ),
        check_tbank_subset_cmap_minimality(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs, used=used,
        ),
        check_tbank_w_array_minimality(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs, used=used,
        ),
        check_tbank_font_subset_exact_closure(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs, used=used,
        ),
        check_tbank_subset_orphan_residue(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs, used=used,
        ),
        check_tbank_f1_maxp_recomputed_to_subset(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs,
        ),
        check_tbank_reassembly_family_v3(
            pdf_bytes, text=text, producer=producer, creator=creator,
            graphs=graphs,
        ),
    ]
    for part in parts:
        out.flags.extend(part.flags)
        for k, v in part.stats.items():
            if k not in out.stats:
                out.stats[k] = v
        out.diagnostics.extend(part.diagnostics)
    return out
