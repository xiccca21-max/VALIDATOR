"""
Font-layer and amount-field validation for T-Bank receipts.

Профили: detector/corpus_profiles.py (23 оригинала Receipt*.pdf, июнь 2026).
Layout classic — все оригиналы: «Итого» F2, сумма F2, рубль F3.
Каналы: sbp (СБП) / phone (внутрибанк) / card (по карте) — разный F1 subset и content stream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    CONTENT_PROFILE_CARD,
    CONTENT_PROFILE_PHONE,
    CONTENT_PROFILE_SBP,
    detect_receipt_channel,
    F1_CID_CLUSTERS,
    F1_CID_ENVELOPE,
    F2_CID_CLUSTERS,
    F2_CID_RANGE,
    TBANK_CLASSIC_LAYOUT,
)
from .pdf_forensics import ForensicResult, Weight, _BF1_RE, _BF2_RE, _BFCHAR_RE, _BFRANGE_RE
from .structure import find_streams, is_content_stream

try:
    import fitz
except ImportError:
    fitz = None

_TM_RE = re.compile(rb"1 0 0 1 (-?\d+\.?\d*) (-?\d+\.?\d*) Tm")
_TF_RE = re.compile(rb"/(\S+)\s+([\d.]+)\s+Tf")
_TJ_RE = re.compile(rb"(\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f]+>)\s*TJ?")
_OBJ_HDR_RE = re.compile(rb"(\d+)\s+0\s+obj")
_FONT_RES_RE = re.compile(rb"/(F\d+)\s+(\d+)\s+0\s+R")
_W_BLOCK_RE = re.compile(rb"/W\s*\[")

# Базовые поля шаблона (layout-специфичные поля подставляются при детекте)
_TBANK_FONT_PROFILE = {
    "template": "tbank_jasper_receipt",
    "total_label_x": TBANK_CLASSIC_LAYOUT["total_label_x"],
    "top_amount_y_delta": 2.0,
    "top_amount_gap_x": (40.0, 250.0),
    "details_label_font": "F1",
    "details_amount_font": "F1",
    "content_decoded_min": CONTENT_PROFILE_SBP["content_decoded_min"],
    "content_decoded_max": CONTENT_PROFILE_SBP["content_decoded_max"],
    "content_raw_min": CONTENT_PROFILE_SBP["content_raw_min"],
    "content_raw_max": CONTENT_PROFILE_SBP["content_raw_max"],
    "total_label_width": (25.0, 130.0),
    "f1_cid_count_range": (F1_CID_ENVELOPE[0], F1_CID_ENVELOPE[1]),
    "f3_cid_count_range": (0, 2),
    "total_equals_amount_only": True,
}

_LAYOUT_CLASSIC = {
    **TBANK_CLASSIC_LAYOUT,
    "f2_cid_count_range": F2_CID_RANGE,
}

_LAYOUT_V2 = {
    "layout": "v2",
    "total_label_font": "F1",
    "total_label_size": 16.0,
    "top_amount_font": "F2",
    "top_amount_size": 16.0,
    "ruble_font": "F3",
    "f2_cid_count_range": (4, 12),
}

# Кластерные профили F1 — из corpus_profiles (23 оригинала)
_F1_CLUSTER = F1_CID_CLUSTERS

_OBSERVED_F1_CIDS = frozenset(_F1_CLUSTER.keys())
_F1_CID_ENVELOPE_LOCAL = F1_CID_ENVELOPE

# Известные опечатки / подозрительные ФИО (контентный слой, не PDF)
_NAME_TYPO_PATTERNS = [
    re.compile(r"Гагарип\b", re.I),
]


@dataclass
class TextRun:
    text: str
    font: str
    font_size: float
    x: float
    y: float
    width: float
    right_edge: float
    cids: list[int] = field(default_factory=list)
    raw_tokens: list[bytes] = field(default_factory=list)


def _decode_paren_text(tok: bytes) -> str:
    try:
        inner = tok[1:-1]
        out = []
        i = 0
        while i < len(inner):
            c = inner[i:i + 1]
            if c == b"\\" and i + 1 < len(inner):
                n = inner[i + 1:i + 2]
                if n == b"n":
                    out.append("\n")
                elif n == b"r":
                    out.append("\r")
                elif n == b"t":
                    out.append("\t")
                elif n == b"(":
                    out.append("(")
                elif n == b")":
                    out.append(")")
                elif n == b"\\":
                    out.append("\\")
                else:
                    out.append(n.decode("latin1", "replace"))
                i += 2
            else:
                out.append(c.decode("latin1", "replace"))
                i += 1
        return "".join(out)
    except Exception:
        return ""


def _cids_from_token(tok: bytes) -> list[int]:
    if tok.startswith(b"<") and tok.endswith(b">"):
        hexs = tok[1:-1].decode("ascii", "ignore")
        return [int(hexs[i:i + 4], 16) for i in range(0, len(hexs) - 3, 4)]
    if tok.startswith(b"(") and tok.endswith(b")"):
        cids = []
        for m in re.finditer(rb"\\(\d{3})", tok):
            cids.append(int(m.group(1), 8) if m.group(1).startswith(b"0") else int(m.group(1)))
        return cids
    return []


def _parse_w_array(blob: bytes) -> dict[int, int]:
    widths: dict[int, int] = {}
    for m in _W_BLOCK_RE.finditer(blob):
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, min(len(blob), start + 16000)):
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
            nums = [int(x) for x in re.findall(rb"\d+", mm.group(2))]
            for k, w in enumerate(nums):
                widths[c0 + k] = w
        arr2 = re.sub(rb"\d+\s*\[[^\]]*\]", b" ", arr)
        for mm in re.finditer(rb"(\d+)\s+(\d+)\s+(\d+)", arr2):
            c1, c2, w = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
            for cid in range(c1, c2 + 1):
                widths[cid] = w
    return widths


def _w_raw_metrics(blob: bytes) -> tuple[int, int, int]:
    """Return (raw_length, space_count, newline_count) for first /W block."""
    for m in _W_BLOCK_RE.finditer(blob):
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, min(len(blob), start + 16000)):
            ch = blob[i:i + 1]
            if ch == b"[":
                depth += 1
            elif ch == b"]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        arr = blob[start:end]
        return len(arr), arr.count(b" "), arr.count(b"\n")
    return 0, 0, 0


def _ttf_glyf_len(ttf: bytes) -> int:
    if len(ttf) < 12:
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


def _cmap_decoded_size(font_blob: bytes, obj_spans: dict[int, bytes]) -> int:
    tu_m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", font_blob)
    if not tu_m:
        desc_m = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", font_blob)
        if desc_m:
            font_blob = obj_spans.get(int(desc_m.group(1)), b"")
            tu_m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", font_blob)
    if not tu_m:
        return 0
    tu_blob = obj_spans.get(int(tu_m.group(1)), b"")
    for raw, dec in find_streams(tu_blob):
        if dec:
            return len(dec)
    return len(tu_blob)


def _fontfile2_bytes(font_blob: bytes, obj_spans: dict[int, bytes]) -> bytes:
    blobs = [font_blob]
    desc_m = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", font_blob)
    if desc_m:
        blobs.append(obj_spans.get(int(desc_m.group(1)), b""))
    for blob in blobs:
        fd_m = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", blob)
        if not fd_m:
            continue
        fd_blob = obj_spans.get(int(fd_m.group(1)), b"")
        ff2_m = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", fd_blob)
        if not ff2_m:
            continue
        ff2_obj = obj_spans.get(int(ff2_m.group(1)), b"")
        for raw, dec in find_streams(ff2_obj):
            if dec and dec[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                return dec
    return b""


def _nearest_cluster(cid: int, table: dict[int, dict]) -> tuple[int, dict] | tuple[None, None]:
    if cid in table:
        return cid, table[cid]
    if not table:
        return None, None
    best = min(table.keys(), key=lambda k: abs(k - cid))
    if abs(best - cid) <= 2:
        return best, table[best]
    return None, None


def _in_range(val: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= val <= bounds[1]


def _interpolate_bounds(cid_n: int, lo_k: int, hi_k: int, field: str) -> tuple[int, int]:
    lo_b = _F1_CLUSTER[lo_k][field]
    hi_b = _F1_CLUSTER[hi_k][field]
    if lo_k == hi_k:
        return lo_b
    t = (cid_n - lo_k) / (hi_k - lo_k)
    return (
        int(lo_b[0] + t * (hi_b[0] - lo_b[0])),
        int(lo_b[1] + t * (hi_b[1] - lo_b[1])),
    )


def _f1_cid_in_envelope(cid_n: int) -> bool:
    lo, hi = _F1_CID_ENVELOPE_LOCAL
    return lo <= cid_n <= hi


def _f1_cluster_bounds(cid_n: int, field: str) -> tuple[int, int] | None:
    """Границы w_len / w_spaces для CID: точный кластер или интерполяция."""
    if cid_n in _F1_CLUSTER:
        return _F1_CLUSTER[cid_n][field]
    keys = sorted(_F1_CLUSTER.keys())
    lo, hi = _F1_CID_ENVELOPE_LOCAL
    if cid_n < lo or cid_n > hi:
        return None
    lo_k = max((k for k in keys if k <= cid_n), default=keys[0])
    hi_k = min((k for k in keys if k >= cid_n), default=keys[-1])
    return _interpolate_bounds(cid_n, lo_k, hi_k, field)


def _f1_neighbor_w_bounds(cid_n: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Ожидаемые w_len и w_spaces для CID (эталон или интерполяция)."""
    w = _f1_cluster_bounds(cid_n, "w_len")
    sp = _f1_cluster_bounds(cid_n, "w_spaces")
    if w and sp:
        return w, sp
    keys = sorted(_F1_CLUSTER.keys())
    return _F1_CLUSTER[keys[0]]["w_len"], _F1_CLUSTER[keys[0]]["w_spaces"]


def _detect_receipt_layout(runs: list[TextRun]) -> str:
    """classic: F2 «Итого» + F3 сумма; v2: F1 «Итого» + F2 сумма."""
    by_y: dict[float, list[TextRun]] = {}
    for r in runs:
        if r.y > 350 and (r.cids or r.text):
            by_y.setdefault(round(r.y, 1), []).append(r)
    for y in sorted(by_y.keys(), reverse=True):
        line = by_y[y]
        fonts = {r.font for r in line}
        if "F1" in fonts and "F2" in fonts:
            f1x = min(r.x for r in line if r.font == "F1")
            f2x = min(r.x for r in line if r.font == "F2")
            if f2x > f1x + 15:
                return "v2"
        if "F2" in fonts and "F3" in fonts:
            f2x = min(r.x for r in line if r.font == "F2")
            f3x = min(r.x for r in line if r.font == "F3")
            if f3x > f2x:
                return "classic"
    return "classic"


def _runs_plain_text(runs: list[TextRun]) -> str:
    """Текст из content stream (fallback, если fitz.get_text() пустой/битый)."""
    lines: list[str] = []
    for r in sorted(runs, key=lambda x: (-x.y, x.x)):
        t = (r.text or "").strip()
        if not t:
            continue
        if "Итого" in t or t.isprintable():
            lines.append(t)
    return "\n".join(lines)


def _layer_has_total_label(extracted_text: str, runs: list[TextRun],
                           label_run: TextRun | None) -> bool:
    if label_run is not None:
        return True
    if "Итого" in extracted_text:
        return True
    return any("Итого" in (r.text or "") for r in runs)


def _is_sbp_receipt_text(text: str) -> bool:
    """СБП-чек: есть блок идентификатора операции НСПК."""
    return detect_receipt_channel(text) == CHANNEL_SBP


def _content_profile_for_text(text: str, base: dict) -> dict:
    """Размер content stream — min/max по всем оригиналам канала (tbank_invariants.json)."""
    from .tbank_invariants import content_envelope
    p = dict(base)
    p.update(content_envelope(text))
    return p


def _active_profile(runs: list[TextRun], extracted_text: str = "") -> dict:
    layout = _detect_receipt_layout(runs)
    base = dict(_TBANK_FONT_PROFILE)
    base.update(_LAYOUT_V2 if layout == "v2" else _LAYOUT_CLASSIC)
    base["layout"] = layout
    return _content_profile_for_text(extracted_text, base)


def _check_f1_f2_cluster_profiles(
    res: ForensicResult,
    fonts: dict[str, dict],
    obj_spans: dict[int, bytes],
) -> None:
    """§8–10: F1 /W vs соседние CID-кластеры; F2 compact subset (слабый флаг)."""
    finfo = fonts.get("F1")
    if finfo:
        cid_n = len(finfo["widths"]) or len(finfo["cmap"])
        ff2 = _fontfile2_bytes(finfo["blob"], obj_spans)
        w_len = finfo["w_raw_len"]
        w_sp = finfo["w_spaces"]
        res.stats.setdefault("font_cluster", {})["F1"] = {
            "cid": cid_n, "fontfile2": len(ff2),
            "glyf": _ttf_glyf_len(ff2), "w_len": w_len, "w_spaces": w_sp,
        }
        if cid_n and w_len and w_sp:
            if not _f1_cid_in_envelope(cid_n):
                res.stats["font_cluster"]["F1"]["cid_out_of_corpus_envelope"] = True
            # /W — зависит от текста чека, не от подлинности; только в stats.
            w_bounds, sp_bounds = _f1_neighbor_w_bounds(cid_n)
            res.stats["font_cluster"]["F1"]["w_expected"] = {
                "w_len": w_bounds, "w_spaces": sp_bounds,
            }

    f2 = fonts.get("F2")
    if f2:
        cid_n = len(f2["widths"]) or len(f2["cmap"])
        ff2 = _fontfile2_bytes(f2["blob"], obj_spans)
        w_len = f2["w_raw_len"]
        res.stats.setdefault("font_cluster", {})["F2"] = {
            "cid": cid_n, "fontfile2": len(ff2),
            "glyf": _ttf_glyf_len(ff2), "w_len": w_len, "w_spaces": f2["w_spaces"],
        }
        lo, hi = F2_CID_RANGE
        if cid_n and cid_n < lo:
            res.stats["font_cluster"]["F2"]["compact_subset"] = True
        # F2 fontfile2/glyf/w_len — только stats


def _check_name_anomalies(text: str, res: ForensicResult) -> None:
    """§18: контентные аномалии ФИО (не отклоняют сами по себе)."""
    lines = [ln.strip() for ln in text.split("\n")]
    names: list[str] = []
    for i, line in enumerate(lines):
        if line == "Отправитель" and i > 0:
            names.append(("sender", lines[i - 1]))
        if line == "Получатель" and i > 0:
            names.append(("receiver", lines[i - 1]))
    for role, name in names:
        if not name or len(name) < 4:
            continue
        for pat in _NAME_TYPO_PATTERNS:
            if pat.search(name):
                code = "SENDER_NAME_TEXT_ANOMALY" if role == "sender" else "RECEIVER_NAME_TEXT_ANOMALY"
                res.add(code, Weight.LOW,
                        f"подозрительное ФИО ({role}): «{name}»")
                break


def _cmap_cids_from_blob(blob: bytes) -> dict[int, str]:
    cid_map: dict[int, str] = {}
    for m in _BFCHAR_RE.finditer(blob):
        for hm in _BF1_RE.finditer(m.group(1)):
            try:
                cid = int(hm.group(1), 16)
                u = bytes.fromhex(hm.group(2).decode()[:4]).decode("utf-16-be", "ignore")
                if u:
                    cid_map[cid] = u
            except Exception:
                pass
    for m in _BFRANGE_RE.finditer(blob):
        for hm in _BF2_RE.finditer(m.group(1)):
            try:
                lo, hi = int(hm.group(1), 16), int(hm.group(2), 16)
                base = int(hm.group(3).decode(), 16)
                for i, cid in enumerate(range(lo, hi + 1)):
                    cid_map[cid] = chr(base + i)
            except Exception:
                pass
    return cid_map


def _font_objects(pdf_bytes: bytes) -> dict[str, dict]:
    """Map resource name (F1/F2/F3) -> {obj_num, base_font, blob, widths, cmap}."""
    res_map: dict[str, int] = {}
    for m in _FONT_RES_RE.finditer(pdf_bytes):
        res_map[m.group(1).decode()] = int(m.group(2))

    obj_spans: dict[int, bytes] = {}
    for m in _OBJ_HDR_RE.finditer(pdf_bytes):
        num = int(m.group(1))
        start = m.start()
        end = pdf_bytes.find(b"endobj", start)
        if end > start:
            obj_spans[num] = pdf_bytes[start:end]

    fonts: dict[str, dict] = {}
    for key, num in res_map.items():
        blob = obj_spans.get(num, b"")
        base_m = re.search(rb"/BaseFont\s*/([^\s/\]]+)", blob)
        base = base_m.group(1).decode("latin1", "replace") if base_m else ""
        widths = _parse_w_array(blob)
        cmap: dict[int, str] = {}
        tu_m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", blob)
        if tu_m:
            tu_blob = obj_spans.get(int(tu_m.group(1)), b"")
            for raw, dec in find_streams(tu_blob):
                if dec:
                    cmap.update(_cmap_cids_from_blob(dec))
            cmap.update(_cmap_cids_from_blob(tu_blob))
        if not widths:
            desc_m = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
            if desc_m:
                desc_blob = obj_spans.get(int(desc_m.group(1)), b"")
                widths = _parse_w_array(desc_blob)
                if not cmap:
                    tu2 = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", desc_blob)
                    if tu2:
                        tu_blob = obj_spans.get(int(tu2.group(1)), b"")
                        for raw, dec in find_streams(tu_blob):
                            if dec:
                                cmap.update(_cmap_cids_from_blob(dec))
        w_len, w_spaces, w_nl = _w_raw_metrics(blob)
        if not w_len:
            desc_m = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
            if desc_m:
                w_len, w_spaces, w_nl = _w_raw_metrics(obj_spans.get(int(desc_m.group(1)), b""))
        fonts[key] = {
            "obj": num,
            "base_font": base,
            "blob": blob,
            "widths": widths,
            "cmap": cmap,
            "w_raw_len": w_len,
            "w_spaces": w_spaces,
            "w_newlines": w_nl,
        }
    return fonts, obj_spans


def _text_width(cids: list[int], widths: dict[int, int], font_size: float) -> float:
    if not cids:
        return 0.0
    scale = font_size / 1000.0
    return sum(widths.get(c, 500) for c in cids) * scale


def parse_text_runs(content: bytes, font_widths: dict[str, dict[int, int]]) -> list[TextRun]:
    runs: list[TextRun] = []
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
        font, fsize, x, y = "", 0.0, 0.0, 0.0
        for line in block.split(b"\n"):
            tf = _TF_RE.search(line)
            if tf:
                font = tf.group(1).decode("latin1", "replace")
                fsize = float(tf.group(2))
            tm = _TM_RE.search(line)
            if tm:
                x, y = float(tm.group(1)), float(tm.group(2))
            for tj in _TJ_RE.finditer(line):
                tok = tj.group(1)
                cids = _cids_from_token(tok)
                text = _decode_paren_text(tok) if tok.startswith(b"(") else ""
                wmap = font_widths.get(font, {})
                w = _text_width(cids, wmap, fsize) if cids else len(text) * fsize * 0.5
                runs.append(TextRun(
                    text=text,
                    font=font,
                    font_size=fsize,
                    x=x,
                    y=y,
                    width=w,
                    right_edge=x + w,
                    cids=cids,
                    raw_tokens=[tok],
                ))
    return runs


def normalize_money(text: str | None) -> int | None:
    """Parse T-Bank money string → integer kopecks (копейки)."""
    if not text:
        return None
    if any(c in text for c in "+()*@"):
        return None
    if re.search(r"\d{2}\.\d{2}\.\d{4}", text):
        return None
    if re.search(r"\*{2,}|№", text):
        return None
    s = text.replace("\u00a0", " ").replace("\u202f", " ")
    s = s.replace("₽", "").replace("i", "").replace("I", "").strip()
    if not re.search(r"\d", s):
        return None
    m = re.search(r"(\d[\d\s]*)(?:[,.](\d{1,2}))?\s*$", s.strip())
    if not m:
        return None
    rubles_str = re.sub(r"\s", "", m.group(1))
    if not rubles_str.isdigit():
        return None
    rubles = int(rubles_str)
    frac = m.group(2)
    kopecks = int(frac.ljust(2, "0")) if frac else 0
    if kopecks >= 100:
        return None
    total = rubles * 100 + kopecks
    if total > 5_000_000_000:  # 50M ₽ cap
        return None
    return total


def format_money_kopecks(kopecks: int) -> str:
    rub = kopecks // 100
    kop = kopecks % 100
    rub_s = f"{rub:,}".replace(",", "\u202f")
    return f"{rub_s},{kop:02d}" if kop else rub_s


def extract_amounts_from_text(text: str) -> dict:
    lines = [ln.strip() for ln in text.split("\n")]
    top = details = commission = None

    for i, line in enumerate(lines):
        if line == "Итого" and i + 1 < len(lines):
            top = normalize_money(lines[i + 1])
            break

    for i, line in enumerate(lines):
        if line == "Сумма" and i > 0:
            details = normalize_money(lines[i - 1])
            break

    for i, line in enumerate(lines):
        if line == "Комиссия" and i + 1 < len(lines):
            nxt = lines[i + 1].lower()
            if "без комиссии" in nxt:
                commission = 0
            else:
                commission = normalize_money(lines[i + 1])
            break

    if top is not None and details is None:
        hits = [normalize_money(ln) for ln in lines[:20]]
        hits = [h for h in hits if h is not None]
        for h in hits:
            if h == top:
                details = h
                break

    return {"top": top, "details": details, "commission": commission}


def _runs_near_y(runs: list[TextRun], y: float, tol: float = 2.0) -> list[TextRun]:
    return [r for r in runs if abs(r.y - y) <= tol]


def _find_total_label_run(runs: list[TextRun], profile: dict) -> TextRun | None:
    candidates = [
        r for r in runs
        if r.font == profile["total_label_font"]
        and abs(r.font_size - profile["total_label_size"]) < 0.5
        and profile["total_label_x"][0] <= r.x <= profile["total_label_x"][1]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.y)


def _font_used_cids(runs: list[TextRun], font_key: str) -> set[int]:
    out: set[int] = set()
    for r in runs:
        if r.font == font_key:
            out.update(r.cids)
    return out


def _cyrillic_chars(chars: set[str]) -> set[str]:
    return {c for c in chars if "\u0400" <= c <= "\u04FF" and c.isalpha()}


def run_font_layer_checks(pdf_bytes: bytes, *, bank: str = "tbank") -> ForensicResult:
    res = ForensicResult(template="unknown")
    if bank != "tbank":
        return res

    content = b""
    raw_content = b""
    for raw, dec in find_streams(pdf_bytes):
        if is_content_stream(dec):
            content = dec
            raw_content = raw
            break

    if not content:
        res.checks["font_layers"] = "no_content"
        return res

    fonts, obj_spans = _font_objects(pdf_bytes)
    font_widths = {k: v["widths"] for k, v in fonts.items()}
    runs = parse_text_runs(content, font_widths)

    extracted_text = ""
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            extracted_text = doc[0].get_text()
            doc.close()
        except Exception:
            pass
    if not extracted_text.strip():
        extracted_text = _runs_plain_text(runs)

    profile = _active_profile(runs, extracted_text)
    res.template = profile["template"]
    res.stats["layout"] = profile.get("layout", "classic")
    res.stats["text_runs"] = [
        {"text": r.text[:20], "font": r.font, "size": r.font_size,
         "x": r.x, "y": r.y, "width": round(r.width, 2), "right_edge": round(r.right_edge, 2)}
        for r in runs[:40]
    ]
    res.stats["font_resources"] = {
        k: {"base": v["base_font"], "w_cids": len(v["widths"]), "cmap_cids": len(v["cmap"]),
            "w_raw_len": v["w_raw_len"], "w_spaces": v["w_spaces"]}
        for k, v in fonts.items()
    }

    # ── §5–10 F1/F2 кластерные профили FontFile2, glyf, CMap, /W ─────────────
    _check_f1_f2_cluster_profiles(res, fonts, obj_spans)

    # ── §13 object 12 / content stream metrics ───────────────────────────────
    res.stats["object12"] = {
        "raw_len": len(raw_content),
        "decoded_len": len(content),
        "bt_count": content.count(b"BT"),
        "tj_count": len(_TJ_RE.findall(content)),
        "tm_count": len(_TM_RE.findall(content)),
        "font_switches": len(_TF_RE.findall(content)),
    }
    o12 = res.stats["object12"]
    # Метрики object12 — только stats; вердикт по корпусу min–max не ставим (вариативность оригиналов).
    res.stats["object12"]["decoded_in_corpus"] = (
        profile["content_decoded_min"] <= o12["decoded_len"] <= profile["content_decoded_max"]
    )

    res.stats["receipt_channel"] = detect_receipt_channel(extracted_text)

    if extracted_text:
        _check_name_anomalies(extracted_text, res)

    # ── §1–2 «Итого» font layer ───────────────────────────────────────────────
    label_run = _find_total_label_run(runs, profile)

    if not _layer_has_total_label(extracted_text, runs, label_run):
        res.add("TOTAL_LABEL_FONT_LAYER_MISMATCH", Weight.MEDIUM,
                "слово «Итого» не найдено в текстовом слое")

    if label_run:
        res.stats["total_label_run"] = {
            "font": label_run.font, "size": label_run.font_size,
            "x": label_run.x, "y": label_run.y,
            "width": round(label_run.width, 2), "right_edge": round(label_run.right_edge, 2),
        }
        if label_run.font != profile["total_label_font"]:
            res.add("TOTAL_LABEL_FONT_LAYER_MISMATCH", Weight.HIGH,
                    f"«Итого» выведено через {label_run.font}, ожидался {profile['total_label_font']}")
        lo, hi = profile["total_label_width"]
        if label_run.width and not (lo <= label_run.width <= hi):
            res.add("TOTAL_LABEL_WIDTH_PROFILE_SHIFT", Weight.LOW,
                    f"ширина «Итого» {label_run.width:.1f}pt вне профиля {lo}–{hi}")
        if len(label_run.raw_tokens) > 1:
            res.add("TOTAL_LABEL_FRAGMENTED_TEXT_RUN", Weight.MEDIUM,
                    f"«Итого» разбито на {len(label_run.raw_tokens)} Tj-операций")
        same_line = _runs_near_y(runs, label_run.y, profile["top_amount_y_delta"])
        fonts_on_line = {r.font for r in same_line if r.cids or r.text}
        if len(fonts_on_line) > 3:
            res.add("TOTAL_LINE_TEXT_RUN_ANOMALY", Weight.LOW,
                    f"на строке «Итого» слишком много смен шрифта: {sorted(fonts_on_line)}")
    elif "Итого" in extracted_text:
        res.add("TOTAL_LABEL_FONT_LAYER_MISMATCH", Weight.MEDIUM,
                f"«Итого» в тексте есть, но не найден профильный text run "
                f"{profile['total_label_font']} {profile['total_label_size']}pt")

    # FONT_SWITCH_INSIDE_WORD: same y, adjacent runs different fonts with small x gap
    by_y: dict[float, list[TextRun]] = {}
    for r in runs:
        if r.cids:
            by_y.setdefault(round(r.y, 1), []).append(r)
    for y, line_runs in by_y.items():
        line_runs.sort(key=lambda r: r.x)
        for a, b in zip(line_runs, line_runs[1:]):
            if a.font != b.font and (b.x - a.right_edge) < 8:
                if y == round(label_run.y, 1) if label_run else -1:
                    res.add("FONT_SWITCH_INSIDE_WORD", Weight.HIGH,
                            f"смена шрифта {a.font}→{b.font} на y={y} в зоне «Итого»")
                    res.add("TOTAL_LABEL_SPLIT_BETWEEN_FONTS", Weight.HIGH,
                            f"метка «Итого» разделена между {a.font} и {b.font}")
                    break

    # ── §3 top amount font layer ──────────────────────────────────────────────
    top_amount_run = None
    if label_run:
        amount_candidates = [
            r for r in _runs_near_y(runs, label_run.y, profile["top_amount_y_delta"])
            if r.font == profile["top_amount_font"]
            and abs(r.font_size - profile["top_amount_size"]) < 0.5
            and r.x > label_run.right_edge + 5
        ]
        if amount_candidates:
            top_amount_run = min(amount_candidates, key=lambda r: r.x)
        else:
            amount_candidates = [
                r for r in _runs_near_y(runs, label_run.y, profile["top_amount_y_delta"])
                if r.font == profile["top_amount_font"] and r.x > label_run.x + 30
            ]
            if amount_candidates:
                top_amount_run = min(amount_candidates, key=lambda r: r.x)

    if top_amount_run:
        res.stats["top_amount_run"] = {
            "font": top_amount_run.font, "text": top_amount_run.text[:20],
            "cid_count": len(top_amount_run.cids), "x": top_amount_run.x,
            "right_edge": round(top_amount_run.right_edge, 2),
        }
        if top_amount_run.font != profile["top_amount_font"]:
            res.add("TOP_AMOUNT_FONT_LAYER_MISMATCH", Weight.HIGH,
                    f"верхняя сумма через {top_amount_run.font}, ожидался {profile['top_amount_font']}")
        if label_run and abs(label_run.y - top_amount_run.y) > profile["top_amount_y_delta"]:
            res.add("TOTAL_AMOUNT_PAIR_LAYOUT_MISMATCH", Weight.MEDIUM,
                    f"«Итого» y={label_run.y} и сумма y={top_amount_run.y} не на одной линии")
        gap = top_amount_run.x - label_run.right_edge if label_run else 0
        if label_run and not (profile["top_amount_gap_x"][0] <= gap <= profile["top_amount_gap_x"][1]):
            res.add("TOTAL_LABEL_AMOUNT_GAP_OUT_OF_PROFILE", Weight.LOW,
                    f"промежуток Итого→сумма {gap:.1f}pt вне профиля")
    elif label_run:
        res.add("TOP_AMOUNT_FONT_LAYER_MISMATCH", Weight.MEDIUM,
                f"верхняя сумма ({profile['top_amount_font']}) не найдена на строке «Итого»")

    # ── §4 amount consistency ─────────────────────────────────────────────────
    amounts = extract_amounts_from_text(extracted_text) if extracted_text else {}
    res.stats["amounts"] = amounts
    if amounts.get("top") is None and "Итого" in extracted_text:
        res.add("TOP_TOTAL_AMOUNT_PARSE_FAILED", Weight.LOW,
                "не удалось извлечь верхнюю сумму из текстового слоя")
    if amounts.get("details") is None and "Сумма" in extracted_text and amounts.get("top") is not None:
        res.add("DETAILS_AMOUNT_PARSE_FAILED", Weight.LOW,
                "не удалось извлечь сумму из блока «Сумма»")
    if amounts.get("top") is not None and amounts.get("details") is not None:
        comm = amounts.get("commission") or 0
        if amounts["top"] != amounts["details"]:
            if not (comm > 0 and amounts["top"] == amounts["details"] + comm):
                res.add("AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS", Weight.HIGH,
                        f"Итого {format_money_kopecks(amounts['top'])} ≠ "
                        f"Сумма {format_money_kopecks(amounts['details'])}"
                        + (f" (+ комиссия {format_money_kopecks(comm)})" if comm else ""))

    # ── §5–8 per-font F1/F2/F3 analysis ───────────────────────────────────────
    for fkey, finfo in fonts.items():
        used = _font_used_cids(runs, fkey)
        cmap_set = set(finfo["cmap"])
        w_set = set(finfo["widths"])
        cmap_chars = set(finfo["cmap"].values())
        res.stats.setdefault("font_sync", {})[fkey] = {
            "used": len(used), "cmap": len(cmap_set), "w": len(w_set),
        }
        if used and cmap_set:
            if used - cmap_set:
                res.add("USED_CID_CMAP_MISMATCH", Weight.HIGH,
                        f"{fkey}: {len(used - cmap_set)} used CID нет в CMap")
                res.add("USED_CID_MISSING_FROM_CMAP", Weight.HIGH,
                        f"{fkey}: используемые CID не покрыты ToUnicode")
        if cmap_set and w_set:
            extra_w = w_set - cmap_set
            missing_w = cmap_set - w_set
            if extra_w:
                res.add("W_EXTRA_CID", Weight.MEDIUM,
                        f"{fkey}: {len(extra_w)} CID в /W без CMap")
            if missing_w:
                res.add("W_MISSING_CID", Weight.MEDIUM,
                        f"{fkey}: {len(missing_w)} CID в CMap без /W")
            if extra_w or missing_w:
                res.add("CMAP_W_MISMATCH", Weight.HIGH,
                        f"{fkey}: рассинхрон CMap ({len(cmap_set)}) и /W ({len(w_set)})")
        if used and w_set and used - w_set:
            res.add("USED_CID_MISSING_FROM_W", Weight.HIGH,
                    f"{fkey}: {len(used - w_set)} used CID отсутствуют в /W")

        if re.search(rb"\d\s+\[", finfo["blob"]):
            res.add("W_ARRAY_PRETTY_PRINTED", Weight.HIGH,
                    f"{fkey}: /W с пробелами — сторонняя сериализация")
            res.add("WIDTH_TABLE_RAW_PROFILE_SHIFT", Weight.MEDIUM,
                    f"{fkey}: pretty-printed /W")

    # F2 subset vs amount digits
    f2 = fonts.get("F2", {})
    f2_used = _font_used_cids(runs, "F2")
    f2_chars = set(f2.get("cmap", {}).values())
    f2_cyr = _cyrillic_chars(f2_chars)
    if f2_cyr - {"И", "т", "о", "г"} and len(f2_cyr) > 6:
        res.add("F2_CONTAINS_UNEXPECTED_CYRILLIC", Weight.MEDIUM,
                f"F2 CMap содержит лишнюю кириллицу: {''.join(sorted(f2_cyr)[:12])}")
    if f2_cyr and profile["total_label_font"] == "F2":
        extra_cyr = f2_cyr - set("Итого")
        if len(extra_cyr) > 2:
            res.add("F2_CONTAINS_TOTAL_LABEL_GLYPHS", Weight.LOW,
                    f"F2 содержит кириллицу сверх «Итого»: {''.join(sorted(extra_cyr)[:8])}")

    if amounts.get("top") is not None and f2_used:
        digit_chars = set(str(amounts["top"]))
        f2_digits = {c for c in f2_chars if c.isdigit()}
        if digit_chars - f2_digits - {" "}:
            res.add("F2_MISSING_AMOUNT_GLYPHS", Weight.MEDIUM,
                    f"F2 CMap не покрывает цифры суммы {amounts['top']}")

    f2_count = len(f2_used)
    lo, hi = profile.get("f2_cid_count_range", (4, 12))
    if f2_count and not (lo <= f2_count <= hi):
        res.add("F2_CID_COUNT_OUT_OF_PROFILE", Weight.LOW,
                f"F2 used CID={f2_count}, профиль {lo}–{hi}")

    f1_used = _font_used_cids(runs, "F1")
    lo1, hi1 = profile.get("f1_cid_count_range", (40, 120))
    if f1_used and not (lo1 <= len(f1_used) <= hi1):
        res.add("F1_FONT_SUBSET_SIZE_NOT_MATCHING_CID_CLUSTER", Weight.LOW,
                f"F1 used CID={len(f1_used)}, профиль {lo1}–{hi1}")

    # Right-edge drift: только логируем в stats, без скоринга на оригинальном разбросе Jasper
    value_runs = [r for r in runs if r.font == "F1" and 8.5 <= r.font_size <= 9.5 and r.x > 100]
    if len(value_runs) >= 3:
        edges = [r.right_edge for r in value_runs]
        med = sorted(edges)[len(edges) // 2]
        res.stats["value_right_edges"] = {
            "median": round(med, 1),
            "drift_count": sum(1 for e in edges if abs(e - med) > 25),
        }

    # ── §15–16 ruble layer ───────────────────────────────────────────────────
    ruble_runs = [r for r in runs if r.font == profile["ruble_font"] and r.y > 300]
    if ruble_runs and top_amount_run:
        ruble_on_top = [r for r in ruble_runs if abs(r.y - top_amount_run.y) < 2]
        if not ruble_on_top:
            res.add("RUBLE_FONT_LAYER_MISMATCH", Weight.LOW,
                    "символ рубля не на одной линии с верхней суммой")
        for r in ruble_on_top:
            if b"(i)" in b"".join(r.raw_tokens) or r.text == "i":
                res.stats["ruble_glyph"] = "ALSRubl (i)"
            break

    # ── §17 commission logic (template: Итого == Сумма, комиссия отдельно) ───
    if profile.get("total_equals_amount_only"):
        if amounts.get("top") is not None and amounts.get("commission") is not None:
            if amounts["commission"] > 0 and amounts.get("details") is not None:
                if amounts["top"] != amounts["details"]:
                    pass  # already flagged
                elif amounts["top"] != amounts["details"] + amounts["commission"]:
                    res.add("TOTAL_AMOUNT_COMMISSION_LOGIC_MISMATCH", Weight.LOW,
                            "Итого не согласуется с Сумма+Комиссия для шаблона")

    # ── checks summary (§20) ──────────────────────────────────────────────────
    res.checks["font_layers"] = "ok"
    res.checks["amount_consistency"] = (
        "ok" if not any(f.code == "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS" for f in res.flags)
        else "fail"
    )
    res.checks["total_label_layer"] = (
        "ok" if not any("TOTAL_LABEL" in f.code for f in res.flags) else "warning"
    )
    res.checks["f2_profile"] = (
        "ok" if not any(f.code.startswith("F2_") for f in res.flags) else "warning"
    )
    res.checks["f1_w_profile"] = (
        "ok" if not any("F1_W" in f.code or "REGULAR_WIDTH" in f.code for f in res.flags)
        else "warning"
    )
    res.checks["right_edges"] = (
        "ok" if not any("RIGHT_EDGE" in f.code for f in res.flags) else "minor_warning"
    )
    res.checks["cmap_w_sync"] = (
        "ok" if not any(f.code in ("CMAP_W_MISMATCH", "USED_CID_CMAP_MISMATCH") for f in res.flags)
        else "warning"
    )

    return res


def font_layers_to_log_dict(result: ForensicResult) -> dict:
    return {
        "template": result.template,
        "score": result.score,
        "flags": result.codes(),
        "checks": result.checks,
        "stats": result.stats,
    }
