"""
T-Bank corpus-spec checks (128 originals profile).

Implements missing layers from the full validation spec:
  PDF shell (exact metadata), F3 hard profile, F1/F2 table/W hashes,
  extended content-stream operators, ToUnicode counts, coordinates,
  right-edge / baseline rhythm (soft), stream entropy (soft), family detection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import zlib
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    SUBTYPE_INTRABANK_CLIENT,
    detect_receipt_channel,
    detect_receipt_subtype,
)
from .ff2_pool import extract_ff2_fingerprints
from .font_layers import _font_objects, _w_raw_metrics
from .pdf_forensics import _ttf_tables
from .structure import content_stream_bytes, find_streams

_DATA_DIR = Path(__file__).with_name("data") / "tbank_template"
_COORD_TOL = 1.5
_RIGHT_TOL = 2.0
_BASELINE_TOL = 2.0

_W_BLOCK_RE = re.compile(rb"/W\s*\[")
_TRAILER_RE = re.compile(rb"trailer\s*<<", re.I)
_SUBJECT_RE = re.compile(rb"/Subject\s*\(([^)]*)\)|/Subject\s*<([^>]*)>")
_PREV_RE = re.compile(rb"/Prev\s+\d+")


@dataclass
class CorpusFlag:
    code: str
    detail: str
    hard: bool = True
    soft_weight: int = 0
    category: str = ""


@dataclass
class CorpusSpecResult:
    flags: list[CorpusFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    category_scores: dict = field(default_factory=dict)
    family: str = ""


def _load_spec() -> dict:
    path = _DATA_DIR / "corpus_spec.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_label_clusters() -> list[dict]:
    path = _DATA_DIR / "label_clusters.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def detect_tbank_family(text: str) -> str:
    """SBP / PHONE / CARD / TBANK_CLIENT / NOCOMM."""
    channel = detect_receipt_channel(text)
    subtype = detect_receipt_subtype(text)
    if subtype == SUBTYPE_INTRABANK_CLIENT:
        return "tbank_client"
    if channel == CHANNEL_SBP:
        return "sbp"
    if channel == CHANNEL_PHONE:
        return "phone"
    if channel == CHANNEL_CARD:
        if "Комиссия" not in text:
            return "nocomm"
        return "card"
    return "phone"


def _font_tounicode_counts(font_blob: bytes, obj_spans: dict[int, bytes]) -> tuple[int, int]:
    tu_m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", font_blob)
    if not tu_m:
        return 0, 0
    tu_blob = obj_spans.get(int(tu_m.group(1)), b"")
    for raw, dec in find_streams(tu_blob):
        if dec:
            tu_blob = dec
            break
    bf = len(re.findall(rb"beginbfchar", tu_blob, re.I))
    br = len(re.findall(rb"beginbfrange", tu_blob, re.I))
    return bf, br


def _table_hash(data: bytes, tag: bytes) -> str:
    tables = _ttf_tables(data)
    if tag not in tables:
        return ""
    off, ln = tables[tag]
    return hashlib.sha256(data[off: off + ln]).hexdigest()[:12]


def _w_raw_blob(blob: bytes) -> bytes:
    for m in _W_BLOCK_RE.finditer(blob):
        start = m.end() - 1
        depth = 0
        for i in range(start, min(len(blob), start + 16000)):
            ch = blob[i:i + 1]
            if ch == b"[":
                depth += 1
            elif ch == b"]":
                depth -= 1
                if depth == 0:
                    return blob[start:i + 1]
    return b""


def _count_ops(content: bytes) -> dict[str, int]:
    """Count PDF operators (BT/Tm/Tj…) outside false positives from text strings."""
    content = re.sub(rb"\((?:\\.|[^\\)])*\)", b"()", content)
    content = re.sub(rb"<[0-9A-Fa-f\s]+>", b"<>", content)
    out: dict[str, int] = {}
    for op in ("BT", "ET", "Tf", "Tm", "Tj", "TJ", "q", "Q", "cm", "Do"):
        pat = re.compile(rf"(?<![A-Za-z]){re.escape(op)}(?![A-Za-z])".encode())
        out[op] = len(pat.findall(content))
    return out


def _page_dims(pdf_bytes: bytes) -> tuple[float | None, float | None]:
    if not fitz:
        return None, None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        r = doc[0].rect
        doc.close()
        return round(r.width, 1), round(r.height, 1)
    except Exception:
        return None, None


def _meta_subject(pdf_bytes: bytes) -> str:
    m = _SUBJECT_RE.search(pdf_bytes)
    if not m:
        return ""
    raw = m.group(1) or m.group(2) or b""
    return raw.decode("latin-1", "replace").strip().strip('"')


def _xref_length(pdf_bytes: bytes) -> int | None:
    if not fitz:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = doc.xref_length()
        doc.close()
        return n
    except Exception:
        return None


def _shell_counts(pdf_bytes: bytes) -> dict:
    eof_count = pdf_bytes.lower().count(b"%%eof")
    trailer_count = len(_TRAILER_RE.findall(pdf_bytes))
    prev_count = len(_PREV_RE.findall(pdf_bytes))
    return {
        "xref_objects": _xref_length(pdf_bytes),
        "eof_count": eof_count,
        "trailer_count": trailer_count,
        "prev_count": prev_count,
    }


def _check_pdf_shell(pdf_bytes: bytes, spec: dict, meta: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    sh = spec.get("shell") or {}
    if not sh:
        return flags

    producer = (meta.get("producer") or "").strip()
    creator = (meta.get("creator") or "").strip()
    subject = _meta_subject(pdf_bytes) or (meta.get("subject") or "").strip().strip('"')
    width, height = _page_dims(pdf_bytes)
    counts = _shell_counts(pdf_bytes)

    exp_prod = sh.get("producer", "")
    if exp_prod and producer != exp_prod:
        flags.append(CorpusFlag(
            "TBANK_SHELL_PRODUCER_MISMATCH",
            f"Producer «{producer}» — ожидается «{exp_prod}»",
            category="pdf_shell",
        ))

    cre_pref = sh.get("creator_prefix", "")
    if cre_pref and not creator.startswith(cre_pref):
        flags.append(CorpusFlag(
            "TBANK_SHELL_CREATOR_MISMATCH",
            f"Creator «{creator[:60]}…» — ожидается JasperReports 6.20.3",
            category="pdf_shell",
        ))

    exp_sub = sh.get("subject", "")
    if exp_sub and subject != exp_sub:
        flags.append(CorpusFlag(
            "TBANK_SHELL_SUBJECT_MISMATCH",
            f"Subject «{subject}» — ожидается «{exp_sub}»",
            category="pdf_shell",
        ))

    exp_w = sh.get("page_width")
    if exp_w is not None and width is not None and abs(width - float(exp_w)) > 0.5:
        flags.append(CorpusFlag(
            "TBANK_SHELL_PAGE_WIDTH",
            f"ширина страницы {width} pt — эталон {exp_w} pt",
            category="pdf_shell",
        ))

    allowed_h = sh.get("page_heights") or []
    if allowed_h and height is not None:
        nearest = min(allowed_h, key=lambda h: abs(float(h) - height))
        if abs(height - float(nearest)) > 3.0:
            flags.append(CorpusFlag(
                "TBANK_SHELL_PAGE_HEIGHT",
                f"высота {height} pt не из whitelist {allowed_h}",
                hard=False,
                soft_weight=10,
                category="pdf_shell",
            ))

    xref_wl = sh.get("xref_objects") or []
    xref_n = counts["xref_objects"]
    if xref_wl and xref_n is not None and xref_n not in xref_wl:
        flags.append(CorpusFlag(
            "TBANK_SHELL_XREF_COUNT",
            f"xref objects={xref_n}, допустимо {xref_wl}",
            hard=False,
            soft_weight=8,
            category="pdf_shell",
        ))

    if sh.get("eof_count") is not None and counts["eof_count"] != sh["eof_count"]:
        flags.append(CorpusFlag(
            "TBANK_SHELL_EOF_COUNT",
            f"%%EOF={counts['eof_count']}, ожидается {sh['eof_count']}",
            category="pdf_shell",
        ))

    if sh.get("prev_count") is not None and counts["prev_count"] != sh["prev_count"]:
        flags.append(CorpusFlag(
            "TBANK_SHELL_PREV_PRESENT",
            f"/Prev встречается {counts['prev_count']} раз",
            category="pdf_shell",
        ))

    return flags


def _check_f3_hard(pdf_bytes: bytes, spec: dict, stats: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    f3spec = (spec.get("fonts") or {}).get("F3") or {}
    if not f3spec:
        return flags

    fp = extract_ff2_fingerprints(pdf_bytes)
    if not fp or "F3" not in fp:
        return flags

    f3 = fp["F3"]
    stats["F3"] = f3
    exp_sha = f3spec.get("font_sha_prefix", "")
    if exp_sha and not f3["sha256"].startswith(exp_sha):
        flags.append(CorpusFlag(
            "TBANK_F3_HASH_MISMATCH",
            f"F3 SHA {f3['sha256'][:16]} ≠ corpus {exp_sha}",
            category="fonts",
        ))

    exp_len = f3spec.get("font_len")
    if exp_len and f3["size"] != exp_len:
        flags.append(CorpusFlag(
            "TBANK_F3_SIZE_MISMATCH",
            f"F3 size={f3['size']} — эталон {exp_len}",
            category="fonts",
        ))

    if TTFont and exp_sha:
        from .ff2_pool import _extract_fontfile2
        ttf = _extract_fontfile2(pdf_bytes, "F3")
        if ttf:
            try:
                tt = TTFont(BytesIO(ttf))
                ng = tt["maxp"].numGlyphs
                stats["F3_numGlyphs"] = ng
                if ng != f3spec.get("numGlyphs", 23):
                    flags.append(CorpusFlag(
                        "TBANK_F3_NUMGLYPHS",
                        f"F3 numGlyphs={ng}, эталон 23",
                        category="fonts",
                    ))
            except Exception:
                pass
    return flags


def _check_f1_f2_tables(pdf_bytes: bytes, spec: dict, stats: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    fonts_spec = spec.get("fonts") or {}
    from .ff2_pool import _extract_fontfile2

    for layer in ("F1", "F2"):
        lspec = fonts_spec.get(layer) or {}
        if not lspec:
            continue
        ttf = _extract_fontfile2(pdf_bytes, layer)
        if not ttf:
            continue
        layer_stats: dict = {"size": len(ttf)}
        if TTFont:
            try:
                tt = TTFont(BytesIO(ttf))
                ng = tt["maxp"].numGlyphs
                layer_stats["numGlyphs"] = ng
                exp_ng = lspec.get("numGlyphs")
                if exp_ng and ng != exp_ng:
                    flags.append(CorpusFlag(
                        f"TBANK_{layer}_NUMGLYPHS",
                        f"{layer} numGlyphs={ng}, эталон {exp_ng}",
                        hard=False,
                        soft_weight=8,
                        category="fonts",
                    ))
            except Exception:
                pass

        for tbl, key in (("hmtx", "hmtx_hashes"), ("head", "head_hashes"), ("maxp", "maxp_hashes")):
            h = _table_hash(ttf, tbl.encode())
            if h:
                layer_stats[f"{tbl}_hash"] = h
                allowed = set(lspec.get(key) or [])
                if allowed and h not in allowed:
                    flags.append(CorpusFlag(
                        f"TBANK_{layer}_{tbl.upper()}_DRIFT",
                        f"{layer} {tbl} hash {h} не в corpus whitelist",
                        hard=False,
                        soft_weight=5,
                        category="fonts",
                    ))

        stats[layer] = layer_stats

        fonts, obj_spans = _font_objects(pdf_bytes)
        fo = fonts.get(layer) or {}
        w_blob = _w_raw_blob(fo.get("blob") or b"")
        if w_blob:
            wh = hashlib.sha256(w_blob).hexdigest()[:16]
            layer_stats["w_hash"] = wh
            allowed_w = set(lspec.get("w_hashes") or [])
            if allowed_w and wh not in allowed_w:
                flags.append(CorpusFlag(
                    f"TBANK_{layer}_W_ARRAY_UNKNOWN",
                    f"{layer} /W hash {wh} не в corpus ({len(allowed_w)} эталонов)",
                    hard=False,
                    soft_weight=8,
                    category="fonts",
                ))

        blob = fo.get("blob") or b""
        bf, br = _font_tounicode_counts(blob, obj_spans)
        layer_stats["bfchar"] = bf
        layer_stats["bfrange"] = br
        exp_bf = lspec.get("bfchar_count") or [0]
        exp_br = lspec.get("bfrange_count") or [1]
        if bf not in exp_bf or br not in exp_br:
            flags.append(CorpusFlag(
                f"TBANK_{layer}_TOUNICODE_COUNTS",
                f"{layer} ToUnicode bfchar={bf} bfrange={br} — эталон bfchar=0 bfrange=1",
                hard=False,
                soft_weight=5,
                category="glyphs",
            ))

    return flags


def _check_operators(pdf_bytes: bytes, spec: dict, height: float | None, stats: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    if height is None:
        return flags
    content = content_stream_bytes(pdf_bytes)
    if not content:
        return flags

    ops = _count_ops(content)
    stats["operators"] = ops

    by_h = spec.get("operators_by_height") or {}
    if not by_h:
        return flags
    prof_key = min(by_h.keys(), key=lambda k: abs(float(k) - height))
    profile = by_h.get(prof_key)
    if not profile:
        return flags

    for op, modes in profile.items():
        if op not in ops:
            continue
        if op in ("q", "Q", "cm", "Do", "Tf"):
            continue
        allowed = {int(k) for k in modes}
        if allowed and ops[op] not in allowed:
            flags.append(CorpusFlag(
                "TBANK_OPERATOR_FINGERPRINT",
                f"высота {height}: {op}={ops[op]}, допустимо {sorted(allowed)}",
                hard=False,
                soft_weight=15,
                category="streams",
            ))
            break

    if ops.get("BT") != ops.get("ET") and ops.get("BT") and ops.get("ET"):
        flags.append(CorpusFlag(
            "TBANK_BT_ET_MISMATCH",
            f"BT={ops['BT']} ≠ ET={ops['ET']}",
            category="streams",
        ))
    return flags


def _stream_entropy(raw: bytes, decoded: bytes) -> dict:
    if not raw:
        return {}
    ratio = len(decoded) / max(len(raw), 1)
    freq = Counter(decoded)
    n = len(decoded)
    ent = -sum((c / n) * math.log2(c / n) for c in freq.values()) if n else 0.0
    return {"zlib_ratio": round(ratio, 3), "compressed_size": len(raw), "entropy": round(ent, 3)}


def _check_entropy(pdf_bytes: bytes, stats: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    for raw, dec in find_streams(pdf_bytes):
        if not dec or b"Tj" not in dec:
            continue
        metrics = _stream_entropy(raw, dec)
        stats["stream_entropy"] = metrics
        if raw[:2] not in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
            flags.append(CorpusFlag(
                "TBANK_STREAM_ZLIB_HEADER",
                f"content stream zlib header {raw[:2]!r} — эталон \\x78\\x9c",
                hard=False,
                soft_weight=10,
                category="streams",
            ))
        break
    return flags


def _label_spans(text_dict: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for block in text_dict.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            line_text = "".join((sp.get("text") or "") for sp in line.get("spans") or [])
            for sp in line.get("spans") or []:
                t = (sp.get("text") or "").strip()
                bbox = sp.get("bbox") or [0, 0, 0, 0]
                entry = {
                    "x0": round(bbox[0], 2),
                    "y0": round(bbox[1], 2),
                    "right": round(bbox[2], 2),
                }
                if t and t not in out:
                    out[t] = entry
                if line_text.strip() and line_text.strip() not in out:
                    out[line_text.strip()] = entry
    return out


def _check_layout(pdf_bytes: bytes, height: float | None, stats: dict) -> list[CorpusFlag]:
    flags: list[CorpusFlag] = []
    if not fitz or height is None:
        return flags

    clusters = _load_label_clusters()
    if not clusters:
        return flags

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        td = doc[0].get_text("dict")
        doc.close()
    except Exception:
        return flags

    spans = _label_spans(td)
    stats["label_spans"] = {k: v for k, v in spans.items() if len(k) < 40}

    label_aliases = {
        "Сумма": ("Сумма",),
        "Комиссия": ("Комиссия",),
        "Отправитель": ("Отправитель",),
        "Получатель": ("Получатель", "Карта получателя"),
        "Банк": ("Банк получателя", "Банк"),
        "Телефон": ("Телефон получателя", "Телефон"),
        "Квитанция": ("Квитанция",),
    }

    for row in clusters:
        label = row.get("label") or ""
        heights = row.get("heights") or {}
        if str(float(height)) not in heights and str(int(height)) not in heights:
            continue

        aliases = label_aliases.get(label, (label,))
        sp = None
        for alias in aliases:
            if alias in spans:
                sp = spans[alias]
                break
        if not sp:
            continue

        x0_lo, y0_lo = row.get("x0_min"), row.get("y0_min")
        y0_hi = row.get("y0_max")
        r_lo, r_hi = row.get("right_min"), row.get("right_max")
        if y0_hi is not None and abs(float(y0_hi) - float(y0_lo)) > 5:
            continue
        if x0_lo is not None:
            if abs(sp["x0"] - x0_lo) > _COORD_TOL or abs(sp["y0"] - y0_lo) > _COORD_TOL:
                flags.append(CorpusFlag(
                    "TBANK_COORDINATE_DRIFT",
                    f"«{label}» ({sp['x0']}, {sp['y0']}) — эталон ({x0_lo}, {y0_lo})",
                    hard=False,
                    soft_weight=8,
                    category="coordinates",
                ))
                break
        if r_lo is not None and r_hi is not None:
            if abs(sp["right"] - r_lo) > _RIGHT_TOL:
                flags.append(CorpusFlag(
                    "TBANK_RIGHT_EDGE_DRIFT",
                    f"«{label}» right={sp['right']} — эталон {r_lo}",
                    hard=False,
                    soft_weight=10,
                    category="coordinates",
                ))

    baseline_pairs = [
        ("Итого", "Комиссия"),
        ("Комиссия", "Отправитель"),
        ("Отправитель", "Получатель"),
        ("Получатель", "Банк получателя"),
    ]
    spec = _load_spec()
    dy_spec = spec.get("baseline_dy") or {}
    for a, b in baseline_pairs:
        sa = spans.get(a)
        sb = spans.get(b)
        if not sa or not sb:
            continue
        dy = round(sb["y0"] - sa["y0"], 2)
        key = f"{a}->{b}"
        row = dy_spec.get(key)
        if not row:
            continue
        if dy < row["min"] - _BASELINE_TOL or dy > row["max"] + _BASELINE_TOL:
            flags.append(CorpusFlag(
                "TBANK_BASELINE_DRIFT",
                f"Δy {key}={dy} pt — corpus [{row['min']}, {row['max']}]",
                hard=False,
                soft_weight=8,
                category="coordinates",
            ))
            break

    return flags


def _category_totals(flags: list[CorpusFlag]) -> dict[str, int]:
    caps = {"pdf_shell": 20, "fonts": 25, "glyphs": 20, "streams": 15, "coordinates": 10, "logic": 10}
    scores = {k: 0 for k in caps}
    for f in flags:
        cat = f.category or "logic"
        w = 20 if f.hard else f.soft_weight
        scores[cat] = min(scores.get(cat, 0) + w, caps.get(cat, 10))
    return scores


def run_tbank_corpus_spec_checks(
    pdf_bytes: bytes,
    text: str = "",
    meta: dict | None = None,
) -> CorpusSpecResult:
    """Run corpus-spec layers not covered elsewhere."""
    res = CorpusSpecResult()
    spec = _load_spec()
    if not spec:
        res.stats["corpus_spec"] = "unavailable"
        return res

    meta = meta or {}
    if fitz and not meta.get("producer"):
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            meta = dict(doc.metadata or {})
            doc.close()
        except Exception:
            pass

    if not text and fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = doc[0].get_text()
            doc.close()
        except Exception:
            text = ""

    res.family = detect_tbank_family(text)
    res.stats["family"] = res.family

    width, height = _page_dims(pdf_bytes)
    res.stats["page_width"] = width
    res.stats["page_height"] = height
    res.stats.update(_shell_counts(pdf_bytes))

    res.flags.extend(_check_pdf_shell(pdf_bytes, spec, meta))
    res.flags.extend(_check_f3_hard(pdf_bytes, spec, res.stats))
    res.flags.extend(_check_f1_f2_tables(pdf_bytes, spec, res.stats))
    res.flags.extend(_check_operators(pdf_bytes, spec, height, res.stats))
    res.flags.extend(_check_entropy(pdf_bytes, res.stats))
    res.flags.extend(_check_layout(pdf_bytes, height, res.stats))

    res.category_scores = _category_totals(res.flags)
    res.stats["category_scores"] = res.category_scores
    return res
