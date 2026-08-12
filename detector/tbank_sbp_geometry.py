"""K-TBANK-SBP-GEOMETRY-001 — raw content-stream SBP ID alignment (T-Bank only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import fitz
except ImportError:
    fitz = None

from .font_layers import _font_objects
from .structure import content_stream_bytes, is_content_stream
from .structure import find_streams

_TOLERANCE_PT = 0.05
_DEFAULT_R = 250.0
_R_MIN = 235.0
_R_MAX = 265.0

_TM_RE = re.compile(rb"1 0 0 1 (-?[\d.]+) (-?[\d.]+) Tm")
_TF_RE = re.compile(rb"/(F\d+) ([\d.]+) Tf")
_TJ_PAREN_RE = re.compile(rb"\(([^)]*)\)Tj")
_TJ_HEX_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*TJ?")
_TC_RE = re.compile(rb"(-?[\d.]+) Tc")
_TW_RE = re.compile(rb"(-?[\d.]+) Tw")
_TZ_RE = re.compile(rb"(-?[\d.]+) Tz")
_TD_RE = re.compile(rb"(-?[\d.]+) (-?[\d.]+) Td")
_TD_UP_RE = re.compile(rb"(-?[\d.]+) (-?[\d.]+) TD")

_SBP_LINE1_RE = re.compile(r"^[AB][0-9A-Z]{10,28}$")
_SBP_LINE2_RE = re.compile(r"^[0-9]{4,6}$")


def _is_sbp_value_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(_SBP_LINE1_RE.fullmatch(compact) or _SBP_LINE2_RE.fullmatch(compact))
_LABEL_ID = "идентификатор операции"
_LABEL_SBP = "сбп"


@dataclass
class SbpLineGeom:
    text: str
    x: float
    y: float
    font: str
    font_size: float
    tm: tuple[float, float]
    stream_offset: int
    width: float
    end_x: float
    right_boundary: float
    deviation: float
    overflow: float
    cids: list[int] = field(default_factory=list)


@dataclass
class GeometryFlag:
    code: str
    detail: str
    rule_id: str = ""
    line: SbpLineGeom | None = None


@dataclass
class GeometryResult:
    flags: list[GeometryFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    lines: list[SbpLineGeom] = field(default_factory=list)

    def add(self, code: str, detail: str, *, rule_id: str = "", line: SbpLineGeom | None = None) -> None:
        self.flags.append(GeometryFlag(code, detail, rule_id=rule_id or code, line=line))


def _cids_be(raw: bytes) -> list[int]:
    if len(raw) < 2:
        return []
    if len(raw) % 2:
        raw = raw[:-1]
    return [(raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2)]


def _unescape_pdf_string(raw: bytes) -> bytes:
    """Decode PDF literal string escapes; preserve raw bytes for Identity-H CID pairs."""
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == 0x5C and i + 1 < len(raw):
            n = raw[i + 1]
            if n in (0x6E, 0x72, 0x74, 0x62, 0x66):  # n r t b f
                out.append({0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0C}[n])
                i += 2
                continue
            if n in (0x28, 0x29, 0x5C):
                out.append(n)
                i += 2
                continue
            if 0x30 <= n <= 0x37:
                j = i + 1
                octd = bytearray()
                while j < len(raw) and j < i + 4 and 0x30 <= raw[j] <= 0x37:
                    octd.append(raw[j])
                    j += 1
                if octd:
                    out.append(int(octd, 8))
                    i = j
                    continue
            out.append(n)
            i += 2
            continue
        out.append(raw[i])
        i += 1
    return bytes(out)


def _font_dw(fmeta: dict) -> int:
    blob = fmeta.get("blob") or b""
    m = re.search(rb"/DW\s+(-?\d+)", blob)
    if m:
        return int(m.group(1))
    desc = fmeta.get("descendant_blob") or b""
    m = re.search(rb"/DW\s+(-?\d+)", desc)
    if m:
        return int(m.group(1))
    return 1000


def _decode_cid_text(cids: list[int], cmap: dict[int, str]) -> str:
    return "".join(cmap.get(c, "") for c in cids)


def _glyph_advance(
    cid: int,
    widths: dict[int, int],
    font_size: float,
    *,
    dw: int = 1000,
    tc: float = 0.0,
    tw: float = 0.0,
    tz: float = 100.0,
) -> float:
    scale = font_size / 1000.0 * (tz / 100.0)
    w = widths.get(cid, dw)
    return (w + tw) * scale + tc * font_size


def _line_advance(
    cids: list[int],
    widths: dict[int, int],
    font_size: float,
    *,
    dw: int = 1000,
    tc: float = 0.0,
    tw: float = 0.0,
    tz: float = 100.0,
    tj_adjusts: list[float] | None = None,
) -> float:
    total = 0.0
    adjusts = tj_adjusts or []
    for i, c in enumerate(cids):
        total += _glyph_advance(c, widths, font_size, dw=dw, tc=tc, tw=tw, tz=tz)
        if i < len(adjusts):
            total += adjusts[i] * font_size / 1000.0
    return total


def _token_cids(tok: bytes) -> list[int]:
    if tok.startswith(b"<") and tok.endswith(b">"):
        hexs = tok[1:-1].decode("ascii", "ignore")
        return [int(hexs[i:i + 4], 16) for i in range(0, len(hexs) - 3, 4)]
    return _cids_be(_unescape_pdf_string(tok))


def _parse_tj_line(line: bytes) -> list[tuple[bytes, float]]:
    """Extract Tj/TJ operands: raw string bytes + TJ adjustment in text space."""
    out: list[tuple[bytes, float]] = []
    arr = re.search(rb"\[(.*)\]\s*TJ", line, re.S)
    if arr:
        body = arr.group(1)
        pos = 0
        while pos < len(body):
            while pos < len(body) and body[pos:pos + 1] in b" \t\r\n":
                pos += 1
            if pos >= len(body):
                break
            if body[pos:pos + 1] == b"(":
                depth = 0
                j = pos
                while j < len(body):
                    ch = body[j:j + 1]
                    if ch == b"(" and (j == pos or body[j - 1:j] != b"\\"):
                        depth += 1
                    elif ch == b")" and body[j - 1:j] != b"\\":
                        depth -= 1
                        if depth == 0:
                            out.append((body[pos + 1:j], 0.0))
                            pos = j + 1
                            break
                    j += 1
                else:
                    break
                continue
            hm = re.match(rb"<([0-9A-Fa-f]+)>", body[pos:])
            if hm:
                out.append((b"<" + hm.group(1) + b">", 0.0))
                pos += hm.end()
                continue
            nm = re.match(rb"(-?\d+(?:\.\d+)?)", body[pos:])
            if nm and out:
                out[-1] = (out[-1][0], float(nm.group(1)))
                pos += nm.end()
                continue
            pos += 1
        return out
    for m in _TJ_PAREN_RE.finditer(line):
        out.append((m.group(1), 0.0))
    for m in _TJ_HEX_RE.finditer(line):
        out.append((b"<" + m.group(1) + b">", 0.0))
    return out


def _parse_content_runs(content: bytes, fonts: dict[str, dict]) -> list[dict]:
    """Parse BT/ET blocks into positioned text runs with raw-calculated end_x."""
    runs: list[dict] = []
    pos = 0
    while True:
        start = content.find(b"BT", pos)
        if start < 0:
            break
        end = content.find(b"ET", start)
        if end < 0:
            break
        block = content[start:end + 2]
        pos = end + 2

        font = "F1"
        font_size = 9.0
        x = y = 0.0
        tc = tw = 0.0
        tz = 100.0
        line_x = line_y = 0.0

        for line in block.split(b"\n"):
            tf = _TF_RE.search(line)
            if tf:
                font = tf.group(1).decode("latin1", "replace")
                font_size = float(tf.group(2))

            tm = _TM_RE.search(line)
            if tm:
                x = float(tm.group(1))
                y = float(tm.group(2))
                line_x, line_y = x, y

            m = _TC_RE.search(line)
            if m:
                tc = float(m.group(1))
            m = _TW_RE.search(line)
            if m:
                tw = float(m.group(1))
            m = _TZ_RE.search(line)
            if m:
                tz = float(m.group(1))

            td = _TD_RE.search(line) or _TD_UP_RE.search(line)
            if td:
                line_x += float(td.group(1))
                line_y += float(td.group(2))

            for tok, tj_adj in _parse_tj_line(line):
                fmeta = fonts.get(font, {})
                widths = fmeta.get("widths", {})
                dw = _font_dw(fmeta)
                cmap = fmeta.get("cmap", {})
                cids = _token_cids(tok)
                if not cids:
                    continue
                adjusts = [tj_adj] * max(len(cids), 1) if tj_adj else None
                width = _line_advance(
                    cids, widths, font_size, dw=dw, tc=tc, tw=tw, tz=tz,
                    tj_adjusts=adjusts,
                )
                text = _decode_cid_text(cids, cmap)
                end_x = line_x + width
                runs.append({
                    "text": text,
                    "x": line_x,
                    "y": line_y,
                    "font": font,
                    "font_size": font_size,
                    "tm": (x, y),
                    "width": width,
                    "end_x": end_x,
                    "cids": cids,
                    "tj_raw_hex": tok.hex(),
                    "stream_offset": start,
                })
                line_x = end_x
                if tj_adj:
                    line_x += tj_adj * font_size / 1000.0
    return runs


def _norm_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _fitz_layout(pdf_bytes: bytes) -> tuple[dict[str, float], list[dict]]:
    """Label Y positions and SBP ID lines from fitz (secondary parser)."""
    labels: dict[str, float] = {}
    sbp_lines: list[dict] = []
    if not fitz:
        return labels, sbp_lines
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_dict = doc[0].get_text("dict") if doc.page_count else {}
        doc.close()
    except Exception:
        return labels, sbp_lines

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()
            low = _norm_label(txt)
            bbox = line.get("bbox") or (0, 0, 0, 0)
            y = float(bbox[1])
            if _LABEL_ID in low:
                labels["id"] = y
            elif low == _LABEL_SBP:
                labels["sbp"] = y
            compact = re.sub(r"\s+", "", txt)
            if _is_sbp_value_text(compact):
                xs = [sp["bbox"][0] for sp in line.get("spans", []) if sp.get("bbox")]
                xrs = [sp["bbox"][2] for sp in line.get("spans", []) if sp.get("bbox")]
                sbp_lines.append({
                    "text": compact,
                    "y": y,
                    "x": min(xs) if xs else 0.0,
                    "fitz_end_x": max(xrs) if xrs else 0.0,
                })
    return labels, sbp_lines


def _find_sbp_block(
    runs: list[dict],
    *,
    fitz_sbp: list[dict],
) -> tuple[bool, bool, list[dict]]:
    """Match raw content-stream runs to fitz-located SBP ID lines by text."""
    has_id_label = any(
        _LABEL_ID in _norm_label(r["text"]) and r["x"] < 100 for r in runs
    )
    has_sbp_label = any(
        _norm_label(r["text"]) == _LABEL_SBP and r["x"] < 100 for r in runs
    )

    if len(fitz_sbp) < 2:
        return has_id_label, has_sbp_label, []

    raw_by_text: dict[str, dict] = {}
    for r in runs:
        compact = re.sub(r"\s+", "", r["text"])
        if _is_sbp_value_text(compact):
            raw_by_text[compact] = r

    ordered: list[dict] = []
    for fl in sorted(fitz_sbp, key=lambda x: len(x["text"]), reverse=True):
        raw = raw_by_text.get(fl["text"])
        if raw:
            ordered.append(raw)

    if len(ordered) < 2:
        return has_id_label, has_sbp_label, []

    return has_id_label, has_sbp_label, ordered[:2]


def _right_boundary(runs: list[dict], exclude: list[dict]) -> float:
    skip = {(round(r["y"], 2), round(r["x"], 2)) for r in exclude}
    edges: list[float] = []
    for r in runs:
        key = (round(r["y"], 2), round(r["x"], 2))
        if key in skip:
            continue
        if r["font"] != "F1":
            continue
        if r["x"] < 100:
            continue
        if not (8.5 <= r["font_size"] <= 9.5):
            continue
        if r["end_x"] < _R_MIN or r["end_x"] > _R_MAX:
            continue
        edges.append(r["end_x"])
    if not edges:
        return _DEFAULT_R
    near_default = [e for e in edges if abs(e - _DEFAULT_R) <= 0.15]
    if len(near_default) >= 3:
        return sorted(near_default)[len(near_default) // 2]
    return sorted(edges)[len(edges) // 2]


def _fitz_sbp_lines(pdf_bytes: bytes) -> list[tuple[str, float]]:
    if not fitz:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_dict = doc[0].get_text("dict") if doc.page_count else {}
        doc.close()
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()
            compact = re.sub(r"\s+", "", txt)
            if not _is_sbp_value_text(compact):
                continue
            xs = [sp["bbox"][2] for sp in line.get("spans", []) if sp.get("bbox")]
            if xs:
                out.append((compact, max(xs)))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _confirm_with_fitz(
    pdf_bytes: bytes,
    lines: list[SbpLineGeom],
    opid: str,
) -> dict:
    """Secondary parser + visual renderer parity."""
    fitz_lines = _fitz_sbp_lines(pdf_bytes)
    joined = "".join(ln.text for ln in lines)
    stats = {
        "fitz_lines": [{"text": t, "end_x": round(x, 3)} for t, x in fitz_lines],
        "stream_joined": joined,
        "opid_match": bool(
            opid and joined and (
                joined == opid
                or opid.startswith(joined)
                or joined in opid
                or (len(lines) >= 2 and lines[0].text + lines[1].text == opid)
            )
        ),
    }
    return stats


def _format_flag_detail(ln: SbpLineGeom) -> str:
    return (
        f"rule_id=K-TBANK-SBP-GEOMETRY-001; object=Field:SBP ID; stream=/Contents; "
        f"font={ln.font} {ln.font_size:g}pt; Tm=({ln.tm[0]:g},{ln.tm[1]:g}); "
        f"width={ln.width:.3f}; right_boundary={ln.right_boundary:.3f}; "
        f"end_x={ln.end_x:.3f}; deviation={ln.deviation:+.3f}; "
        f"overflow={ln.overflow:+.3f}; text={ln.text}"
    )


def check_tbank_sbp_geometry(
    pdf_bytes: bytes,
    opid: str,
    text: str = "",
) -> GeometryResult:
    """
    Raw content-stream geometry for SBP ID right-edge alignment.
    Confirmed by fitz text-layer positions and visible ID parity.
    """
    res = GeometryResult()
    content = content_stream_bytes(pdf_bytes)
    if not content:
        for raw, dec in find_streams(pdf_bytes):
            if is_content_stream(dec):
                content = dec
                break
    if not content:
        res.stats["parse_failed"] = "no_content_stream"
        return res

    fonts, _ = _font_objects(pdf_bytes)
    if "F1" not in fonts:
        res.stats["parse_failed"] = "no_F1"
        return res

    label_y, fitz_sbp = _fitz_layout(pdf_bytes)
    res.stats["fitz_labels"] = label_y
    res.stats["fitz_sbp_lines"] = fitz_sbp

    runs = _parse_content_runs(content, fonts)
    res.stats["run_count"] = len(runs)
    has_id_label, has_sbp_label, sbp_runs = _find_sbp_block(runs, fitz_sbp=fitz_sbp)
    res.stats["has_id_label"] = has_id_label or bool(label_y.get("id"))
    res.stats["has_sbp_label"] = has_sbp_label or bool(label_y.get("sbp"))

    if not sbp_runs:
        res.stats["parse_failed"] = "sbp_id_lines_not_found"
        return res

    R = _right_boundary(runs, exclude=sbp_runs)
    res.stats["right_boundary"] = round(R, 3)

    geom_lines: list[SbpLineGeom] = []
    for i, r in enumerate(sbp_runs):
        overflow = r["end_x"] - R
        deviation = r["end_x"] - R
        geom_lines.append(SbpLineGeom(
            text=r["text"],
            x=r["x"],
            y=r["y"],
            font=r["font"],
            font_size=r["font_size"],
            tm=r["tm"],
            stream_offset=r["stream_offset"],
            width=r["width"],
            end_x=r["end_x"],
            right_boundary=R,
            deviation=deviation,
            overflow=overflow,
            cids=r["cids"],
        ))

    res.lines = geom_lines
    res.stats["lines"] = [
        {
            "text": ln.text,
            "x": ln.x,
            "y": ln.y,
            "end_x": round(ln.end_x, 3),
            "right_boundary": round(ln.right_boundary, 3),
            "overflow": round(ln.overflow, 3),
            "deviation": round(ln.deviation, 3),
        }
        for ln in geom_lines
    ]

    parity = _confirm_with_fitz(pdf_bytes, geom_lines, opid)
    res.stats["parity"] = parity
    visible = "".join(t for t, _ in _fitz_sbp_lines(pdf_bytes))
    if opid and visible and visible != opid and opid not in visible and visible not in opid:
        res.stats["visible_mismatch"] = {"stream": "".join(ln.text for ln in geom_lines), "visible": visible}

    if not parity.get("opid_match") and opid:
        res.stats["opid_parity_skipped"] = True
        return res

    violations: list[tuple[str, SbpLineGeom]] = []
    for i, ln in enumerate(geom_lines):
        if ln.overflow > _TOLERANCE_PT:
            violations.append(("overflow", ln))
        if i == len(geom_lines) - 1 and (R - ln.end_x) > _TOLERANCE_PT:
            violations.append(("shortfall", ln))

    if not violations:
        return res

    # Require fitz renderer to not contradict hard geometry (within 0.15 pt slack).
    fitz_map = {t: x for t, x in _fitz_sbp_lines(pdf_bytes)}
    confirmed: list[tuple[str, SbpLineGeom]] = []
    for kind, ln in violations:
        fend = fitz_map.get(ln.text)
        if fend is None:
            confirmed.append((kind, ln))
            continue
        if kind == "overflow" and (fend - R) > _TOLERANCE_PT:
            confirmed.append((kind, ln))
        elif kind == "shortfall" and (R - fend) > _TOLERANCE_PT:
            confirmed.append((kind, ln))

    for kind, ln in confirmed:
        if kind == "overflow":
            detail = (
                f"строка SBP ID выходит за правую границу колонки: {_format_flag_detail(ln)}"
            )
        else:
            detail = (
                f"последняя строка SBP ID не доходит до правой границы: {_format_flag_detail(ln)}"
            )
        res.add("TBANK_SBP_GEOMETRY_MISMATCH", detail, rule_id="K-TBANK-SBP-GEOMETRY-001", line=ln)

    return res
