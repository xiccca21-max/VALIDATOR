"""Live T-Bank serializer-family checks (KNOWN / HARD) — no shadow / rollout.

Decisive codes:
  TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1
  TBANK_CARD_OTHER_INTERNAL_WHITESPACE_PADDING
  TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1
  TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1

Identity blacklists (full-PDF SHA, filename, receipt №, FIO, phone, amount,
card, recipient bank, opid / trailer /ID) are intentionally unused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .corpus_profiles import (
    CHANNEL_SBP,
    SUBTYPE_CARD_NUMBER,
    SUBTYPE_INTRABANK_CLIENT,
    detect_receipt_channel,
    detect_receipt_subtype,
)
from .structure import content_stream_bytes, find_streams, is_content_stream
from .tbank_corpus_spec import detect_tbank_family
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_keywords_generation import NEW_TAIL, _keywords_raw, _keywords_tail
from .tbank_reassembly_family_v3 import (
    _composite_closure,
    resolve_font_graph,
)

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover
    TTFont = None  # type: ignore

RULE_SBP = "K-TBANK-KNOWN-FAKE-SBP-SERIALIZER-V1"
RULE_CARD_OTHER = "A-TBANK-CARD-OTHER-INTERNAL-WHITESPACE-PADDING"
RULE_CARD_TBANK = "K-TBANK-KNOWN-FAKE-CARD-TBANK-SERIALIZER-V1"
RULE_NOCOMM = "K-TBANK-KNOWN-FAKE-NOCOMM-SERIALIZER-V1"

CODE_SBP = "TBANK_KNOWN_FAKE_SBP_SERIALIZER_V1"
CODE_CARD_OTHER = "TBANK_CARD_OTHER_INTERNAL_WHITESPACE_PADDING"
CODE_CARD_TBANK = "TBANK_KNOWN_FAKE_CARD_TBANK_SERIALIZER_V1"
CODE_NOCOMM = "TBANK_KNOWN_FAKE_NOCOMM_SERIALIZER_V1"

_PDF_WS = frozenset(b" \t\r\n\f\x00")
_DATE_FULL_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
)
_OBJ_BODY_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.DOTALL)
_OPERATOR_RE = re.compile(
    rb"(?:"
    rb"/(?:[A-Za-z][A-Za-z0-9._]*)|"
    rb"[-+]?(?:\d+\.?\d*|\.\d+)|"
    rb"\((?:\\.|[^\\()])*\)|"
    rb"<(?:[0-9A-Fa-f\s]*)>|"
    rb"\[|\]|"
    rb"[A-Za-z'\"*]{1,3}"
    rb")"
)


@dataclass
class FamilyFlag:
    code: str
    detail: str
    rule_id: str
    tier: str  # KNOWN | A
    group: str = "serializer_family"


@dataclass
class SerializerFamiliesResult:
    flags: list[FamilyFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


def _pdf_text(pdf: bytes) -> str:
    try:
        import fitz

        doc = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text or ""
    except Exception:
        return ""


def visible_second_from_text(text: str) -> int | None:
    """Seconds from a visible HH:MM:SS timestamp only (not HH:MM → forced 0)."""
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _DATE_FULL_RE.search(line)
        if m:
            return int(m.group(6))
        if line and not line[0].isdigit():
            break
    m = _DATE_FULL_RE.search(raw)
    return int(m.group(6)) if m else None


def _page_content_pair(pdf: bytes) -> tuple[bytes, bytes, int | None, int | None]:
    """Largest page content stream: (raw, decoded, objnum, pdf_offset)."""
    best_raw = b""
    best_dec = b""
    best_obj: int | None = None
    best_off: int | None = None
    for m in _OBJ_BODY_RE.finditer(pdf):
        body = m.group(0)
        # reuse find_streams on the object body via local decompress
        for raw, dec in find_streams(body):
            if not dec:
                continue
            if not (
                is_content_stream(dec)
                or (b"BT" in dec and (b"Tj" in dec or b"TJ" in dec))
            ):
                continue
            if len(dec) > len(best_dec):
                best_raw = raw
                best_dec = dec
                best_obj = int(m.group(1))
                best_off = m.start()
    if not best_dec:
        dec = content_stream_bytes(pdf) or b""
        return b"", dec, None, None
    return best_raw, best_dec, best_obj, best_off


def canonicalize_external_whitespace(data: bytes) -> bytes:
    """Collapse consecutive external PDF whitespace to a single 0x20.

    Literal strings, hex strings and comments are copied verbatim.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x25:  # %
            j = i
            while j < n and data[j] not in (0x0A, 0x0D):
                j += 1
            out.extend(data[i:j])
            i = j
            continue
        if c == 0x28:  # (
            out.append(c)
            i += 1
            depth = 1
            while i < n and depth:
                ch = data[i]
                if ch == 0x5C and i + 1 < n:
                    out.append(ch)
                    out.append(data[i + 1])
                    i += 2
                    continue
                if ch == 0x28:
                    depth += 1
                elif ch == 0x29:
                    depth -= 1
                out.append(ch)
                i += 1
            continue
        if c == 0x3C and i + 1 < n and data[i + 1] != 0x3C:  # <hex>
            out.append(c)
            i += 1
            while i < n and data[i] != 0x3E:
                out.append(data[i])
                i += 1
            if i < n:
                out.append(data[i])
                i += 1
            continue
        if c in _PDF_WS:
            while i < n and data[i] in _PDF_WS:
                i += 1
            out.append(0x20)
            continue
        out.append(c)
        i += 1
    return bytes(out)


def _nearest_operators(data: bytes, offset: int, run_len: int) -> tuple[str, str]:
    """Best-effort previous / next content-stream operator around a WS run."""
    before = data[max(0, offset - 80) : offset]
    after = data[offset + run_len : offset + run_len + 80]
    prev_ops = _OPERATOR_RE.findall(before)
    next_ops = _OPERATOR_RE.findall(after)
    prev = prev_ops[-1].decode("latin1", "replace") if prev_ops else ""
    nxt = next_ops[0].decode("latin1", "replace") if next_ops else ""
    return prev, nxt


def external_whitespace_runs(data: bytes) -> list[dict[str, Any]]:
    """Multi-byte external whitespace runs with operator context."""
    runs: list[dict[str, Any]] = []
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x25:
            while i < n and data[i] not in (0x0A, 0x0D):
                i += 1
            continue
        if c == 0x28:
            i += 1
            depth = 1
            while i < n and depth:
                ch = data[i]
                if ch == 0x5C and i + 1 < n:
                    i += 2
                    continue
                if ch == 0x28:
                    depth += 1
                elif ch == 0x29:
                    depth -= 1
                i += 1
            continue
        if c == 0x3C and i + 1 < n and data[i + 1] != 0x3C:
            i += 1
            while i < n and data[i] != 0x3E:
                i += 1
            if i < n:
                i += 1
            continue
        if c in _PDF_WS:
            j = i
            while j < n and data[j] in _PDF_WS:
                j += 1
            run_len = j - i
            if run_len >= 2:
                prev_op, next_op = _nearest_operators(data, i, run_len)
                runs.append({
                    "offset": i,
                    "length": run_len,
                    "excess": run_len - 1,
                    "prev_operator": prev_op,
                    "next_operator": next_op,
                })
            i = j
            continue
        i += 1
    return runs


def f2_unique_nonempty_glyph_lengths(ttf: bytes) -> int:
    if not ttf or TTFont is None:
        return 0
    try:
        tt = TTFont(BytesIO(ttf))
        loca = tt["loca"]
        lengths = {
            int(loca[i + 1]) - int(loca[i])
            for i in range(tt["maxp"].numGlyphs)
            if int(loca[i + 1]) - int(loca[i]) > 0
        }
        return len(lengths)
    except Exception:
        return 0


def f2_nonempty_outside_closure(ttf: bytes, cmap_cids: set[int]) -> list[int]:
    if not ttf:
        return []
    try:
        tt = TTFont(BytesIO(ttf))
        loca = tt["loca"]
        nonempty = {
            i
            for i in range(tt["maxp"].numGlyphs)
            if int(loca[i + 1]) - int(loca[i]) > 0
        }
        required = _composite_closure(ttf, set(cmap_cids))
        return sorted(nonempty - required - {0})
    except Exception:
        return []


def profile_gate_serializer(
    pdf: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> tuple[bool, dict[str, Any]]:
    stats: dict[str, Any] = {"profile_id": PROFILE_ID}
    if not claims_confirmed_tbank_profile(
        pdf, producer=producer, creator=creator,
    ):
        stats["skipped"] = "profile_gate"
        return False, stats
    if not text:
        text = _pdf_text(pdf)
    channel = detect_receipt_channel(text)
    subtype = detect_receipt_subtype(text)
    family = detect_tbank_family(text)
    if not subtype:
        stats["skipped"] = "subtype_unknown"
        return False, stats
    raw, dec, objn, off = _page_content_pair(pdf)
    if not dec:
        stats["skipped"] = "no_content_stream"
        return False, stats
    stats.update({
        "channel": channel,
        "subtype": subtype,
        "family": family,
        "content_obj": objn,
        "content_pdf_offset": off,
        "content_raw_length": len(raw),
        "content_decoded_length": len(dec),
    })
    return True, stats


def collect_serializer_metrics(
    pdf: bytes,
    *,
    text: str = "",
) -> dict[str, Any]:
    if not text:
        text = _pdf_text(pdf)
    raw, dec, objn, off = _page_content_pair(pdf)
    can = canonicalize_external_whitespace(dec) if dec else b""
    excess = len(dec) - len(can) if dec else 0
    runs = external_whitespace_runs(dec) if dec else []
    vs = visible_second_from_text(text)
    tail = _keywords_tail(_keywords_raw(pdf))
    channel = detect_receipt_channel(text)
    subtype = detect_receipt_subtype(text)
    family = detect_tbank_family(text)

    f2_uniq = 0
    f2_outside: list[int] = []
    f1_cmap_n = 0
    f2_cmap_n = 0
    f1_w_n = 0
    f2_w_n = 0
    f1_tu_cr: float | None = None

    graphs = resolve_font_graph(pdf)
    g2 = graphs.get("F2")
    g1 = graphs.get("F1")
    if g2 and g2.fontfile2_decoded:
        f2_uniq = f2_unique_nonempty_glyph_lengths(g2.fontfile2_decoded)
        cmap_cids = set(g2.tounicode or {})
        f2_cmap_n = len(cmap_cids)
        f2_w_n = len(g2.widths or {})
        f2_outside = f2_nonempty_outside_closure(g2.fontfile2_decoded, cmap_cids)
    if g1:
        f1_cmap_n = len(g1.tounicode or {})
        f1_w_n = len(g1.widths or {})
        # Use find_streams raw length (matches /Length); _stream_payload may
        # keep a trailing newline and understate the compression ratio.
        if g1.tounicode_num:
            for m in _OBJ_BODY_RE.finditer(pdf):
                if int(m.group(1)) != int(g1.tounicode_num):
                    continue
                for sraw, sdec in find_streams(m.group(0)):
                    if sraw and sdec:
                        f1_tu_cr = len(sdec) / len(sraw)
                        break
                break
        if f1_tu_cr is None:
            tu_raw = g1.tounicode_raw or b""
            tu_dec = g1.tounicode_decoded or b""
            if tu_raw and tu_dec:
                f1_tu_cr = len(tu_dec) / len(tu_raw)

    cr = (len(dec) / len(raw)) if raw and dec else None
    return {
        "channel": channel,
        "subtype": subtype,
        "family": family,
        "visible_second": vs,
        "keywords_tail": tail,
        "content_obj": objn,
        "content_pdf_offset": off,
        "content_raw_length": len(raw),
        "content_decoded_length": len(dec),
        "content_decoded_mod4": len(dec) % 4 if dec else None,
        "content_compression_ratio": cr,
        "canonicalized_external_whitespace_length": len(can),
        "external_whitespace_excess": excess,
        "whitespace_runs": runs,
        "f2_unique_nonempty_glyph_lengths": f2_uniq,
        "f2_nonempty_outside_closure": f2_outside,
        "f2_nonempty_outside_closure_count": len(f2_outside),
        "f1_cmap_cardinality": f1_cmap_n,
        "f2_cmap_cardinality": f2_cmap_n,
        "f1_w_cardinality": f1_w_n,
        "f2_w_cardinality": f2_w_n,
        "f1_tounicode_compression_ratio": f1_tu_cr,
    }


def check_tbank_serializer_families_v1(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> SerializerFamiliesResult:
    out = SerializerFamiliesResult()
    if not text:
        text = _pdf_text(pdf_bytes)

    ok, gate = profile_gate_serializer(
        pdf_bytes, text=text, producer=producer, creator=creator,
    )
    out.stats.update(gate)
    if not ok:
        return out

    m = collect_serializer_metrics(pdf_bytes, text=text)
    out.stats.update(m)
    out.evidence["visible_second"] = m["visible_second"]
    out.evidence["external_whitespace_excess"] = m["external_whitespace_excess"]
    out.evidence["content_raw_length"] = m["content_raw_length"]
    out.evidence["content_decoded_length"] = m["content_decoded_length"]
    out.evidence["content_decoded_mod4"] = m["content_decoded_mod4"]
    out.evidence["f2_unique_nonempty_glyph_lengths"] = m[
        "f2_unique_nonempty_glyph_lengths"
    ]
    out.evidence["f2_nonempty_outside_closure"] = m["f2_nonempty_outside_closure"]
    out.evidence["f1_cmap_cardinality"] = m["f1_cmap_cardinality"]
    out.evidence["f2_cmap_cardinality"] = m["f2_cmap_cardinality"]
    out.evidence["f1_w_cardinality"] = m["f1_w_cardinality"]
    out.evidence["f2_w_cardinality"] = m["f2_w_cardinality"]
    out.evidence["keywords_tail"] = m["keywords_tail"]

    channel = m["channel"]
    subtype = m["subtype"]
    family = m["family"]
    vs = m["visible_second"]
    tail = m["keywords_tail"]
    f2u = int(m["f2_unique_nonempty_glyph_lengths"] or 0)
    dec_len = int(m["content_decoded_length"] or 0)
    raw_len = int(m["content_raw_length"] or 0)
    excess = int(m["external_whitespace_excess"] or 0)
    cr = m["content_compression_ratio"]
    tur = m["f1_tounicode_compression_ratio"]

    # --- A. SBP serializer family ---
    # Research also noted decoded_content_length % 4 == 3; that residue is not
    # stable on the confirmed 5×5 set (mods 1/2/3), so it is telemetry only.
    # Decisive conjunction: SBP + visible_second=0 + DOCS-2035 + F2 uniq ≥11.
    if (
        channel == CHANNEL_SBP
        and vs == 0
        and tail == NEW_TAIL
        and f2u >= 11
    ):
        out.flags.append(FamilyFlag(
            code=CODE_SBP,
            rule_id=RULE_SBP,
            tier="KNOWN",
            detail=(
                f"SBP serializer family v1: visible_second=0, "
                f"keywords_tail={tail}, f2_unique_nonempty_glyph_lengths={f2u}, "
                f"decoded_content_length={dec_len} "
                f"(mod4={m['content_decoded_mod4']}), "
                f"external_whitespace_excess={excess}, "
                f"f2_outside_closure={m['f2_nonempty_outside_closure_count']}, "
                f"raw={raw_len}, F1/F2 CMap={m['f1_cmap_cardinality']}/"
                f"{m['f2_cmap_cardinality']}, "
                f"/W={m['f1_w_cardinality']}/{m['f2_w_cardinality']}"
            ),
        ))

    # --- B. CARD_OTHER internal whitespace padding ---
    if subtype == SUBTYPE_CARD_NUMBER and excess >= 3:
        runs = m["whitespace_runs"]
        run_lines = []
        for r in runs[:24]:
            run_lines.append(
                f"  offset={r['offset']} len={r['length']} "
                f"prev={r['prev_operator']!r} next={r['next_operator']!r}"
            )
        detail = (
            f"CARD_OTHER internal whitespace padding: "
            f"xref content stream obj={m['content_obj']} "
            f"pdf_offset={m['content_pdf_offset']}, "
            f"decoded_length={dec_len}, "
            f"canonicalized_length={m['canonicalized_external_whitespace_length']}, "
            f"excess_bytes={excess}"
        )
        if run_lines:
            detail += "\n" + "\n".join(run_lines)
        out.flags.append(FamilyFlag(
            code=CODE_CARD_OTHER,
            rule_id=RULE_CARD_OTHER,
            tier="A",
            group="content_whitespace",
            detail=detail,
        ))
        out.evidence["card_other_whitespace_runs"] = runs

    # --- C. CARD_TBANK serializer family ---
    # Confirmed fakes include F2 unique nonempty glyph-length cardinality 10
    # with the same CR/TU band; threshold 11 alone misses that branch.
    serializer_branch_tbank = (
        excess >= 1
        or (
            f2u >= 10
            and cr is not None
            and cr > 3.78
            and tur is not None
            and tur > 2.50
        )
    )
    if (
        subtype == SUBTYPE_INTRABANK_CLIENT
        and vs == 0
        and tail == NEW_TAIL
        and 827 <= raw_len <= 830
        and serializer_branch_tbank
    ):
        out.flags.append(FamilyFlag(
            code=CODE_CARD_TBANK,
            rule_id=RULE_CARD_TBANK,
            tier="KNOWN",
            detail=(
                f"CARD_TBANK serializer family v1: visible_second=0, "
                f"keywords_tail={tail}, content_raw_length={raw_len}, "
                f"external_whitespace_excess={excess}, "
                f"f2_unique_nonempty_glyph_lengths={f2u}, "
                f"content_compression_ratio="
                f"{None if cr is None else round(cr, 4)}, "
                f"f1_tounicode_compression_ratio="
                f"{None if tur is None else round(tur, 4)}"
            ),
        ))

    # --- D. NOCOMM serializer family ---
    serializer_branch_nocomm = (
        excess >= 1
        or (
            excess == 0
            and dec_len > 2815
            and raw_len <= 767
        )
    )
    if (
        family == "nocomm"
        and vs == 0
        and tail == NEW_TAIL
        and 765 <= raw_len <= 767
        and serializer_branch_nocomm
    ):
        out.flags.append(FamilyFlag(
            code=CODE_NOCOMM,
            rule_id=RULE_NOCOMM,
            tier="KNOWN",
            detail=(
                f"NOCOMM serializer family v1: visible_second=0, "
                f"keywords_tail={tail}, content_raw_length={raw_len}, "
                f"content_decoded_length={dec_len}, "
                f"external_whitespace_excess={excess}"
            ),
        ))

    return out
