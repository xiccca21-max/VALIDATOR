"""Exact sbp_outgoing + jasper_itext profile gate and HARD contracts.

Rules fire only when ALL of the following match:
  profile_id == sbp_outgoing
  generator_path == jasper_itext
  MediaBox == 300×795
  Creator / Producer exact Jasper 6.18.1 + iText 2.1.7 strings
  content skeleton ∈ atlas sbp_outgoing set

Otherwise these HARDs are skipped. An sbp_outgoing/jasper document that
fails the exact contract is a *near miss*: exact HARDs are skipped, but the
receipt stays classified as Сбер (not «НЕИЗВЕСТНЫЙ ДОКУМЕНТ»).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore

from ..font_layers import _font_objects, _fontfile2_bytes
from ..structure import content_skeleton_hash, content_stream_bytes
from .atlas import atlas_profile
from .types import SberFlag

RULE_ID = "K-SBER-SBP-EXACT-PROFILE-001"

EXACT_CREATOR = (
    "JasperReports Library version 6.18.1-"
    "9d75d1969e774d4f179fb3be8401e98a0e6d1611"
)
EXACT_PRODUCER = "iText 2.1.7 by 1T3XT"
EXACT_MEDIA_W = 300.0
EXACT_MEDIA_H = 795.0
# sber_internal_jasper genuines (n=15): 300×699; a few phone shells 283×588.
_INTERNAL_MEDIA: frozenset[tuple[float, float]] = frozenset({
    (300.0, 699.0),
    (283.0, 588.0),
})

_STATIC_LABEL_ADVANCES: dict[str, float] = {
    "Операция": 46.570,
    "Сумма перевода": 78.640,
    "Комиссия": 44.820,
    "Счёт отправителя": 84.270,
    "Банк получателя": 78.720,
    "ФИО получателя перевода": 126.380,
    "Номер операции в СБП": 109.880,
}
_STATIC_TOL_PT = 0.015

# Internal «Чек по операции» shares the same Tahoma label alphabet.
_INTERNAL_STATIC_LABELS: frozenset[str] = frozenset({
    "Операция",
    "Сумма перевода",
    "Комиссия",
    "Счёт отправителя",
    "ФИО получателя",
    "ФИО отправителя",
})

# Singleton glyf-outline SHAs for static-label alphabet (sbp_outgoing Jasper
# genuines n=44: exactly one outline per char). SEQ near-miss shells keep
# advances/ink-min but transplant foreign Tahoma outlines on О/е/р/а/С/у/…
_STATIC_LABEL_OUTLINES: dict[str, str] = {
    "Б": "7a7d5c27ce07c2ae",
    "И": "f23faf3f6643d874",
    "К": "79e0dd712a9bbb37",
    "Н": "b9a86d4b51d11a5e",
    "О": "13463dc92199cacf",
    "П": "b92bba09c946467d",
    "С": "1852e655f1df30e2",
    "Ф": "2117e58d2cffde0e",
    "а": "1ed02f31c2512c7c",
    "в": "d3528ff800bcfbcd",
    "д": "4f924f6a6c702160",
    "е": "621bb9a02a3fa771",
    "и": "3606277fe66f244b",
    "к": "95693595f812b17c",
    "л": "e11d8168f1d5a0e4",
    "м": "2f448cf61c44c8d4",
    "н": "ee1a052f86683485",
    "о": "c106f51c07aa9566",
    "п": "bbdf5fdff57bcee9",
    "р": "5bb478dc614482ed",
    "с": "909ca4e1761e01a6",
    "т": "8a7e75346f655fd2",
    "у": "f72396184b2ff479",
    "ц": "aaddc77308bbd19d",
    "ч": "2d683bb3a4d4d58d",
    "я": "cd944a75ee57c6cb",
    "ё": "49ee120c00bebe3d",
}

_SEP_TM = (22.24, 697.74)
_SEP_END_X = 289.756
_SEP_TOL_PT = 0.03
_SEP_TF = 12.0

_HEADER_Y = 711.74
_HEADER_CENTER_X = 153.000
# Corpus sbp_outgoing n=41: |center−153| ≤ 0.004. SEQ 180307 = 0.018.
# Keep ±0.01 (margin over Jasper float noise, still below SEQ drift).
_HEADER_CENTER_TOL = 0.01

_AMOUNT_Y = 385.74
_FEE_Y = 345.74
_SPACE_CID = 0x0003
_RUBLE_CID = 0x0D5A
_PERIOD_CID = 0x0011  # '.' in this cmap family — verified via corpus
_CLOSE_PAREN_CID = 0x000C

_FIO_RECV_Y = 604.74
_FIO_SEND_Y = 475.74
_SBP_VALUE_Y = 304.74

_SBP_MARKER_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_RECV_INITIAL_DOT_RE = re.compile(r"[А-ЯЁ]\.\s*$")

_MEDIABOX_RE = re.compile(
    rb"/MediaBox\s*\[\s*([+-]?\d+(?:\.\d+)?)\s+"
    rb"([+-]?\d+(?:\.\d+)?)\s+"
    rb"([+-]?\d+(?:\.\d+)?)\s+"
    rb"([+-]?\d+(?:\.\d+)?)\s*\]"
)
_TF_RE = re.compile(rb"/([^\s]+)\s+([\d.]+)\s+Tf")
_TM_RE = re.compile(rb"1 0 0 1 ([\d.]+) ([\d.]+) Tm")
_TJ_PAREN_RE = re.compile(rb"(\((?:\\.|[^\\)])*\))Tj")


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    analysis_ok: bool = True
    exact_profile: bool = False
    near_miss_unknown: bool = False


def _f(code: str, detail: str) -> SberFlag:
    return SberFlag(
        code=code, detail=detail, tier="HARD", group="sbp_exact", rule_id=RULE_ID,
    )


def parse_mediabox(pdf_bytes: bytes) -> tuple[float, float] | None:
    m = _MEDIABOX_RE.search(pdf_bytes)
    if not m:
        return None
    x0, y0, x1, y1 = (float(m.group(i)) for i in range(1, 5))
    return (abs(x1 - x0), abs(y1 - y0))


def is_exact_sbp_outgoing_jasper(
    pdf_bytes: bytes,
    *,
    profile_id: str,
    generator_path: str,
    creator: str,
    producer: str,
    skeleton: str | None = None,
) -> bool:
    if profile_id != "sbp_outgoing" or generator_path != "jasper_itext":
        return False
    if (creator or "") != EXACT_CREATOR or (producer or "") != EXACT_PRODUCER:
        return False
    mb = parse_mediabox(pdf_bytes)
    if not mb or abs(mb[0] - EXACT_MEDIA_W) > 0.01 or abs(mb[1] - EXACT_MEDIA_H) > 0.01:
        return False
    sk = skeleton if skeleton is not None else content_skeleton_hash(pdf_bytes)
    known = set((atlas_profile("sbp_outgoing").get("content_skeletons") or []))
    return bool(sk) and sk in known


def is_sbp_jasper_near_miss(
    *,
    profile_id: str,
    generator_path: str,
    exact: bool,
) -> bool:
    """Updated/unknown SBP jasper template — do not HARD-fake via exact rules."""
    return (
        profile_id == "sbp_outgoing"
        and generator_path == "jasper_itext"
        and not exact
    )


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
                out.append(int(octal, 8))
                i = j
                continue
            out.extend(nxt)
            i += 2
            continue
        out.append(s[i])
        i += 1
    return bytes(out)


def cids_from_identity_paren(tok: bytes) -> list[int]:
    raw = _decode_pdf_string(tok)
    if len(raw) % 2:
        raw = raw + b"\x00"
    return [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw), 2)]


@dataclass
class _Run:
    x: float
    y: float
    font_size: float
    cids: list[int]
    text: str
    width: float


def _parse_runs(
    content: bytes,
    widths: dict[int, int],
    cmap: dict[int, str],
) -> list[_Run]:
    runs: list[_Run] = []
    pos = 0
    while True:
        s = content.find(b"BT", pos)
        if s < 0:
            break
        e = content.find(b"ET", s)
        if e < 0:
            break
        block = content[s:e + 2]
        pos = e + 2
        font_size = 0.0
        x = y = 0.0
        for line in block.split(b"\n"):
            tf = _TF_RE.search(line)
            if tf:
                font_size = float(tf.group(2))
            tm = _TM_RE.search(line)
            if tm:
                x, y = float(tm.group(1)), float(tm.group(2))
            tj = _TJ_PAREN_RE.search(line)
            if not tj:
                continue
            cids = cids_from_identity_paren(tj.group(1))
            w = sum(widths.get(c, 500) for c in cids) * (font_size / 1000.0)
            text = "".join(cmap.get(c, "") for c in cids)
            runs.append(_Run(x, y, font_size, cids, text, w))
    return runs


def _advance_width(cids: list[int], widths: dict[int, int], font_size: float) -> float:
    return sum(widths.get(c, 500) for c in cids) * (font_size / 1000.0)


def _check_w_quantizer(tt: Any, widths: dict[int, int], out: CheckResult) -> None:
    upem = int(tt["head"].unitsPerEm)
    order = tt.getGlyphOrder()
    bad: list[str] = []
    for cid, w in sorted(widths.items()):
        if cid < 0 or cid >= len(order):
            continue
        adv, _ = tt["hmtx"][order[cid]]
        expected = math.floor(adv * 1000 / upem)
        if int(w) != expected:
            bad.append(f"CID {cid}: /W={w} expected={expected}")
    out.stats["w_quantizer_mismatches"] = len(bad)
    if bad:
        out.flags.append(_f(
            "SBER_FONT_W_QUANTIZER_MISMATCH",
            f"floor(hmtx*1000/upem) ≠ /W ({len(bad)} CID): " + "; ".join(bad[:6]),
        ))


def _glyph_outline_sha(g: Any, glyf: Any) -> str:
    g.expand(glyf)
    ncont = int(getattr(g, "numberOfContours", 0) or 0)
    if ncont < 0:
        comps = tuple(
            (
                c.glyphName,
                int(c.x),
                int(c.y),
                int(getattr(c, "flags", 0)),
            )
            for c in (g.components or [])
        )
        return hashlib.sha256(repr(comps).encode()).hexdigest()[:16]
    if ncont == 0:
        return "empty"
    coords = tuple(
        (int(x), int(y)) for x, y in (getattr(g, "coordinates", None) or ())
    )
    end = tuple(int(x) for x in (getattr(g, "endPtsOfContours", None) or []))
    flags = bytes(getattr(g, "flags", None) or b"")
    return hashlib.sha256(repr((coords, end, flags)).encode()).hexdigest()[:16]


def _check_static_label_outlines(
    tt: Any,
    runs: list[_Run],
    cmap: dict[int, str],
    out: CheckResult,
) -> None:
    """HARD: static label glyph outlines must match singleton Jasper corpus."""
    order = tt.getGlyphOrder()
    glyf = tt["glyf"]
    bad: list[str] = []
    checked = 0
    seen_chars: set[str] = set()
    for run in runs:
        if (
            run.text not in _STATIC_LABEL_ADVANCES
            and run.text not in _INTERNAL_STATIC_LABELS
        ):
            continue
        # SBP labels are 10pt; internal ФИО/Операция often 10pt too.
        if abs(run.font_size - 10.0) >= 0.05:
            continue
        for cid in run.cids:
            ch = cmap.get(cid) or ""
            if len(ch) != 1 or ch not in _STATIC_LABEL_OUTLINES:
                continue
            if ch in seen_chars:
                continue
            if cid < 0 or cid >= len(order):
                continue
            try:
                sha = _glyph_outline_sha(glyf[order[cid]], glyf)
            except Exception:
                continue
            seen_chars.add(ch)
            checked += 1
            expected = _STATIC_LABEL_OUTLINES[ch]
            if sha != expected:
                bad.append(f"{ch!r}={sha}")
    out.stats["static_label_outline_checked"] = checked
    out.stats["static_label_outline_mismatches"] = len(bad)
    if bad:
        out.flags.append(_f(
            "SBER_STATIC_LABEL_OUTLINE_MISMATCH",
            "контуры символов статических лейблов ≠ корпус Jasper/Tahoma "
            f"(mismatch={len(bad)}/{checked}): " + ", ".join(bad[:10])
            + " — SEQ-пересадка outlines при сохранении advances",
        ))


def _check_reverse_closure(
    tt: Any, used_cids: set[int], out: CheckResult,
) -> None:
    order = tt.getGlyphOrder()
    glyf = tt["glyf"]
    closure: set[int] = set(used_cids) | {0}
    stack = list(closure)
    while stack:
        gid = stack.pop()
        if gid < 0 or gid >= len(order):
            continue
        g = glyf[order[gid]]
        if not getattr(g, "isComposite", lambda: False)():
            continue
        for comp in getattr(g, "components", []) or []:
            name = getattr(comp, "glyphName", "")
            if name not in order:
                continue
            cg = order.index(name)
            if cg not in closure:
                closure.add(cg)
                stack.append(cg)

    nonempty: list[int] = []
    composites = 0
    for gid, name in enumerate(order):
        g = glyf[name]
        ncont = int(getattr(g, "numberOfContours", 0) or 0)
        if ncont != 0:  # simple >0 or composite -1
            nonempty.append(gid)
        if ncont < 0:
            composites += 1

    orphans = sorted(set(nonempty) - closure)
    out.stats["used_cids"] = len(used_cids)
    out.stats["glyph_closure"] = len(closure)
    out.stats["nonempty_glyphs"] = len(nonempty)
    out.stats["composite_glyphs"] = composites
    out.stats["orphan_glyphs"] = orphans
    if orphans:
        out.flags.append(_f(
            "SBER_FONT_REVERSE_GLYPH_CLOSURE",
            f"orphan_glyphs={orphans[:20]}"
            + (f" (+{len(orphans) - 20})" if len(orphans) > 20 else ""),
        ))


# sber_internal_jasper genuines (n=10, MediaBox 300×699): contour-nonempty
# glyf ≥75 and composites ≥14. SEQ CLEAN-miss (Документ-2026-08-10) drops to
# 74/13 while keeping used CID count — broken subset packing, not shorter text.
_INTERNAL_NONEMPTY_FLOOR = 75
_INTERNAL_COMPOSITE_FLOOR = 14


def _check_internal_glyf_floors(out: CheckResult) -> None:
    """HARD floors for sber_internal_jasper FontFile2 subset packing."""
    nonempty = out.stats.get("nonempty_glyphs")
    composites = out.stats.get("composite_glyphs")
    if isinstance(nonempty, int) and nonempty < _INTERNAL_NONEMPTY_FLOOR:
        out.flags.append(_f(
            "SBER_INTERNAL_GLYF_NONEMPTY_FLOOR",
            (
                f"contour-nonempty glyphs={nonempty} < "
                f"{_INTERNAL_NONEMPTY_FLOOR} (корпус sber_internal_jasper "
                f"n=10, min=75) — under-subset / чужой FontFile2 packing"
            ),
        ))
    if isinstance(composites, int) and composites < _INTERNAL_COMPOSITE_FLOOR:
        out.flags.append(_f(
            "SBER_INTERNAL_GLYF_COMPOSITE_FLOOR",
            (
                f"composite glyphs={composites} < "
                f"{_INTERNAL_COMPOSITE_FLOOR} (корпус sber_internal_jasper "
                f"n=10, min=14) — потерян composite в subset reassembly"
            ),
        ))


def _check_static_advances(
    runs: list[_Run],
    out: CheckResult,
    *,
    require_all: bool = True,
) -> None:
    found: dict[str, float] = {}
    for run in runs:
        if run.text in _STATIC_LABEL_ADVANCES and abs(run.font_size - 10.0) < 0.01:
            found[run.text] = run.width
    out.stats["static_advances"] = {k: round(v, 5) for k, v in found.items()}
    bad: list[str] = []
    for label, expected in _STATIC_LABEL_ADVANCES.items():
        if label not in found:
            if require_all:
                bad.append(f"{label!r} отсутствует")
            continue
        if abs(found[label] - expected) > _STATIC_TOL_PT:
            bad.append(
                f"{label!r}={found[label]:.5f}pt expected={expected:.3f}pt"
            )
    if bad:
        out.flags.append(_f(
            "SBER_STATIC_TEXT_ADVANCE_MISMATCH",
            "; ".join(bad[:5]),
        ))


def _check_separator(runs: list[_Run], out: CheckResult) -> None:
    hits = [
        r for r in runs
        if abs(r.x - _SEP_TM[0]) < 0.02
        and abs(r.y - _SEP_TM[1]) < 0.02
        and abs(r.font_size - _SEP_TF) < 0.01
    ]
    if not hits:
        out.flags.append(_f(
            "SBER_SEPARATOR_ADVANCE_MISMATCH",
            f"пунктир Tm={_SEP_TM} Tf={_SEP_TF} не найден",
        ))
        return
    end_x = hits[0].x + hits[0].width
    out.stats["separator_end_x"] = round(end_x, 5)
    if abs(end_x - _SEP_END_X) > _SEP_TOL_PT:
        out.flags.append(_f(
            "SBER_SEPARATOR_ADVANCE_MISMATCH",
            f"end_x={end_x:.5f} expected={_SEP_END_X}±{_SEP_TOL_PT}",
        ))


def _check_header_center(runs: list[_Run], out: CheckResult) -> None:
    hits = [r for r in runs if abs(r.y - _HEADER_Y) < 0.05 and r.cids]
    if not hits:
        out.flags.append(_f(
            "SBER_HEADER_DATE_CENTER_MISMATCH",
            f"строка даты Tm.y={_HEADER_Y} не найдена",
        ))
        return
    run = max(hits, key=lambda r: len(r.cids))
    center = run.x + run.width / 2.0
    out.stats["header_center_x"] = round(center, 6)
    out.stats["header_text"] = run.text
    if abs(center - _HEADER_CENTER_X) > _HEADER_CENTER_TOL:
        out.flags.append(_f(
            "SBER_HEADER_DATE_CENTER_MISMATCH",
            f"center_x={center:.6f} expected={_HEADER_CENTER_X}±{_HEADER_CENTER_TOL}",
        ))


def _check_sbp_marker(runs: list[_Run], out: CheckResult) -> None:
    hits = [r for r in runs if abs(r.y - _SBP_VALUE_Y) < 0.05 and r.text.strip()]
    if not hits:
        # fallback: any 32-char SBP-like token
        hits = [r for r in runs if len(r.text.strip()) == 32]
    if not hits:
        out.flags.append(_f(
            "SBER_SBP_MARKER_INVALID",
            "номер операции в СБП не найден в content stream",
        ))
        return
    token = hits[0].text.strip()
    out.stats["sbp_marker"] = token
    if not _SBP_MARKER_RE.match(token):
        out.flags.append(_f(
            "SBER_SBP_MARKER_INVALID",
            f"маркер {token!r} не соответствует ^[AB][0-9A-Z]{{31}}$",
        ))


def _amount_spacing_ok(cids: list[int]) -> bool:
    """After kopecks digits, exactly two SPACE CIDs then RUBLE.

    Contract: <digits>.<2 digits><0003><0003><0D5A>
    Three or more spaces before ₽ must also fail.
    """
    if _RUBLE_CID not in cids:
        return False
    idx = cids.index(_RUBLE_CID)
    if idx < 3:
        return False
    return (
        cids[idx - 1] == _SPACE_CID
        and cids[idx - 2] == _SPACE_CID
        and cids[idx - 3] != _SPACE_CID
    )


def _check_amount_spacing(runs: list[_Run], out: CheckResult) -> None:
    bad: list[str] = []
    for y, label in ((_AMOUNT_Y, "сумма"), (_FEE_Y, "комиссия")):
        hits = [r for r in runs if abs(r.y - y) < 0.05 and r.cids]
        if not hits:
            bad.append(f"{label}: строка Tm.y={y} не найдена")
            continue
        run = hits[0]
        if not _amount_spacing_ok(run.cids):
            bad.append(
                f"{label}: ожидалось <digits>.<cc><0003><0003><0D5A>, "
                f"cids_tail={[hex(c) for c in run.cids[-6:]]} text={run.text!r}"
            )
    if bad:
        out.flags.append(_f(
            "SBER_AMOUNT_RUBLE_SPACING_INVALID",
            "; ".join(bad),
        ))


def _check_header_trailing_pad(runs: list[_Run], out: CheckResult) -> None:
    hits = [r for r in runs if abs(r.y - _HEADER_Y) < 0.05 and r.cids]
    if not hits:
        return
    run = max(hits, key=lambda r: len(r.cids))
    # After closing paren CID, no SPACE.
    if _CLOSE_PAREN_CID in run.cids:
        idx = len(run.cids) - 1 - run.cids[::-1].index(_CLOSE_PAREN_CID)
        trailing = run.cids[idx + 1:]
        if any(c == _SPACE_CID for c in trailing):
            out.flags.append(_f(
                "SBER_HEADER_TRAILING_PADDING",
                f"дата оканчивается пробелом CID после (МСК): "
                f"trail={[hex(c) for c in trailing]}",
            ))
    elif run.cids and run.cids[-1] == _SPACE_CID:
        out.flags.append(_f(
            "SBER_HEADER_TRAILING_PADDING",
            "дата оканчивается CID 0x0003",
        ))


def _check_fio_trailing_pad(runs: list[_Run], out: CheckResult) -> None:
    bad: list[str] = []
    for y, label in ((_FIO_RECV_Y, "получатель"), (_FIO_SEND_Y, "отправитель")):
        hits = [r for r in runs if abs(r.y - y) < 0.05 and r.cids]
        if not hits:
            continue
        run = hits[0]
        if run.cids and run.cids[-1] == _SPACE_CID:
            bad.append(
                f"{label}: хвостовой CID 0x0003 text={run.text!r}"
            )
    if bad:
        out.flags.append(_f(
            "SBER_FIO_TRAILING_PADDING",
            "; ".join(bad),
        ))


def _check_recipient_initial(runs: list[_Run], out: CheckResult) -> None:
    hits = [r for r in runs if abs(r.y - _FIO_RECV_Y) < 0.05 and r.text.strip()]
    if not hits:
        return
    text = hits[0].text.rstrip()
    out.stats["fio_recipient"] = text
    if _RECV_INITIAL_DOT_RE.search(text):
        out.flags.append(_f(
            "SBER_RECIPIENT_INITIAL_PUNCTUATION",
            f"ФИО получателя с точкой у инициала: {text!r}",
        ))


def check_sbp_exact_profile(
    pdf_bytes: bytes,
    *,
    profile_id: str = "",
    generator_path: str = "",
    creator: str = "",
    producer: str = "",
) -> CheckResult:
    out = CheckResult()
    skeleton = content_skeleton_hash(pdf_bytes)
    out.stats["skeleton"] = skeleton
    exact = is_exact_sbp_outgoing_jasper(
        pdf_bytes,
        profile_id=profile_id,
        generator_path=generator_path,
        creator=creator,
        producer=producer,
        skeleton=skeleton,
    )
    out.exact_profile = exact
    out.stats["exact_sbp_outgoing_jasper"] = exact
    out.near_miss_unknown = is_sbp_jasper_near_miss(
        profile_id=profile_id, generator_path=generator_path, exact=exact,
    )
    out.stats["near_miss_unknown"] = out.near_miss_unknown

    # Skeleton atlas novelty must not skip emitter invariants: same Jasper/iText
    # creator·producer·MediaBox as the outgoing corpus, but unknown skeleton,
    # still gets label-advance / spacing HARDs (SEQ near-miss shells).
    # Same shell gate for sber_internal_jasper — SEQ transplants the same
    # foreign Tahoma outlines on Операция/Сумма/… (CLEAN 181446).
    mb = parse_mediabox(pdf_bytes)
    sbp_media_ok = (
        mb is not None
        and abs(mb[0] - EXACT_MEDIA_W) <= 0.01
        and abs(mb[1] - EXACT_MEDIA_H) <= 0.01
    )
    internal_media_ok = bool(
        mb is not None
        and any(
            abs(mb[0] - w) <= 0.01 and abs(mb[1] - h) <= 0.01
            for w, h in _INTERNAL_MEDIA
        )
    )
    meta_ok = (
        (creator or "") == EXACT_CREATOR
        and (producer or "") == EXACT_PRODUCER
    )
    # SBP near-miss shell (795) vs internal Jasper shell (e.g. 699) — different
    # geometry contracts. Never run SBP Tm.y / marker HARDs on internal.
    sbp_shell_ok = bool(meta_ok and out.near_miss_unknown and sbp_media_ok)
    internal_shell_ok = bool(
        meta_ok
        and profile_id == "sber_internal_jasper"
        and generator_path == "jasper_itext"
        and internal_media_ok
    )
    shell_ok = sbp_shell_ok or internal_shell_ok
    out.stats["near_miss_structural"] = bool(shell_ok)
    out.stats["sbp_shell_ok"] = sbp_shell_ok
    out.stats["internal_shell_ok"] = internal_shell_ok
    if not exact and not shell_ok:
        return out

    try:
        fonts, spans = _font_objects(pdf_bytes)
        f1 = fonts.get("F1") or next(iter(fonts.values()), None)
        if not f1:
            out.analysis_ok = False
            out.stats["error"] = "no_font"
            return out
        widths: dict[int, int] = dict(f1.get("widths") or {})
        cmap: dict[int, str] = dict(f1.get("cmap") or {})
        ttf = _fontfile2_bytes(f1.get("blob", b""), spans)
        if not ttf or TTFont is None:
            out.analysis_ok = False
            out.stats["error"] = "no_fontfile2"
            return out
        tt = TTFont(BytesIO(ttf))
        content = content_stream_bytes(pdf_bytes) or b""
        runs = _parse_runs(content, widths, cmap)
        used: set[int] = set()
        for r in runs:
            used.update(r.cids)
        out.stats["runs"] = len(runs)

        _check_w_quantizer(tt, widths, out)
        # Reverse closure is structural (used-CID → composite closure vs
        # nonempty glyf), not atlas-tied. Genuines: 0 orphans. SEQ near-miss
        # shells that pad hmtx/contour to corpus still leave 10+ orphans.
        _check_reverse_closure(tt, used, out)
        if internal_shell_ok:
            _check_internal_glyf_floors(out)
        # Near-miss SEQ keeps ink-min/advances but transplants foreign
        # outlines on static labels (О/е/р/а/С/у/…). Singleton corpus atlas.
        _check_static_label_outlines(tt, runs, cmap, out)
        _check_static_advances(runs, out, require_all=exact)

        # SBP-layout geometry (separator y≈697.74, date y≈711.74, SBP id,
        # amount ruble spacing) — only on exact / SBP-shell MediaBox 300×795.
        if exact or sbp_shell_ok:
            _check_separator(runs, out)
            _check_header_center(runs, out)
            _check_sbp_marker(runs, out)
            _check_amount_spacing(runs, out)
            _check_header_trailing_pad(runs, out)
            _check_fio_trailing_pad(runs, out)
            _check_recipient_initial(runs, out)
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:240]
    return out
