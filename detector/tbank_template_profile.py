"""
Template-profile checks for T-Bank receipts (128 originals corpus).

Uses detector/data/tbank_template/deep_profile.json and label_clusters.json:
page height → BT/Tm/Tj operator counts, decoded stream size, label coordinates.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

from .structure import content_stream_bytes, find_streams, is_content_stream

_DATA_DIR = Path(__file__).with_name("data") / "tbank_template"
_TJ_RE = re.compile(rb"Tj\b")
_TM_RE = re.compile(rb"Tm\b")
_COORD_TOL = 1.5


@dataclass
class TemplateFlag:
    code: str
    detail: str


@dataclass
class TemplateResult:
    flags: list[TemplateFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _load_deep_profile() -> dict:
    path = _DATA_DIR / "deep_profile.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_label_clusters() -> list[dict]:
    path = _DATA_DIR / "label_clusters.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_modes(raw: str) -> dict[int, int]:
    """Parse '[(22, 40), (23, 2)]' → {22: 40, 23: 2}."""
    try:
        pairs = ast.literal_eval(raw)
        return {int(k): int(v) for k, v in pairs}
    except Exception:
        return {}


def _nearest_height(height: float, profiles: list[dict]) -> dict | None:
    if not profiles:
        return None
    return min(profiles, key=lambda p: abs(float(p["height"]) - height))


def _page_height(pdf_bytes: bytes) -> float | None:
    if not fitz:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        rect = doc[0].rect
        doc.close()
        return round(rect.height, 1)
    except Exception:
        return None


def _stream_metrics(content: bytes) -> dict[str, int]:
    return {
        "bt": content.count(b"BT"),
        "tm": len(_TM_RE.findall(content)),
        "tj": len(_TJ_RE.findall(content)),
        "decoded_len": len(content),
    }


def _label_spans(text_dict: dict) -> dict[str, dict]:
    """Map label text → first span bbox/origin."""
    out: dict[str, dict] = {}
    for block in text_dict.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            for sp in line.get("spans") or []:
                t = (sp.get("text") or "").strip()
                if not t or t in out:
                    continue
                bbox = sp.get("bbox") or [0, 0, 0, 0]
                out[t] = {
                    "x0": round(bbox[0], 2),
                    "y0": round(bbox[1], 2),
                    "right": round(bbox[2], 2),
                    "font": sp.get("font", ""),
                }
    return out


def _check_label_coords(spans: dict[str, dict], clusters: list[dict]) -> list[TemplateFlag]:
    flags: list[TemplateFlag] = []
    core = ("Итого", "Перевод", "Статус", "Сумма")
    for row in clusters:
        label = row.get("label") or ""
        if label not in core:
            continue
        sp = spans.get(label)
        if not sp:
            continue
        x0_lo, x0_hi = row.get("x0_min"), row.get("x0_max")
        y0_lo, y0_hi = row.get("y0_min"), row.get("y0_max")
        if x0_lo is None:
            continue
        if abs(sp["x0"] - x0_lo) > _COORD_TOL or abs(sp["y0"] - y0_lo) > _COORD_TOL:
            flags.append(TemplateFlag(
                "TBANK_TEMPLATE_LABEL_DRIFT",
                f"подпись «{label}» на ({sp['x0']}, {sp['y0']}) — "
                f"эталон ({x0_lo}, {y0_lo})",
            ))
            break
    return flags


def run_tbank_template_checks(pdf_bytes: bytes) -> TemplateResult:
    """Hard signals when page-height template BT/Tj or label coords diverge from corpus."""
    res = TemplateResult()
    deep = _load_deep_profile()
    if not deep or not fitz:
        res.stats["template_profile"] = "unavailable"
        return res

    height = _page_height(pdf_bytes)
    res.stats["page_height"] = height
    if height is None:
        return res

    stream_rows = deep.get("stream_by_height") or []
    profile = _nearest_height(height, stream_rows)
    if not profile:
        res.flags.append(TemplateFlag(
            "TBANK_TEMPLATE_HEIGHT_UNKNOWN",
            f"высота страницы {height} pt не встречалась в корпусе оригиналов",
        ))
        return res

    res.stats["template_height"] = profile.get("height")
    content = content_stream_bytes(pdf_bytes)
    if not content:
        return res

    metrics = _stream_metrics(content)
    res.stats.update(metrics)

    prof_h = float(profile["height"])
    if abs(height - prof_h) > 3.0:
        res.flags.append(TemplateFlag(
            "TBANK_TEMPLATE_HEIGHT_MISMATCH",
            f"высота страницы {height} pt не совпадает с ближайшим шаблоном {prof_h} pt",
        ))

    dec_lo = profile.get("decoded_min")
    dec_hi = profile.get("decoded_max")
    if dec_lo and dec_hi and not (dec_lo <= metrics["decoded_len"] <= dec_hi):
        res.flags.append(TemplateFlag(
            "TBANK_TEMPLATE_STREAM_SIZE",
            f"decoded content stream {metrics['decoded_len']} вне профиля "
            f"высоты {prof_h} ({dec_lo}–{dec_hi})",
        ))

    for op, key in (("BT", "bt"), ("Tm", "tm"), ("Tj", "tj")):
        modes_raw = profile.get(f"{op}_modes") or ""
        modes = _parse_modes(modes_raw)
        if modes and metrics[key] not in modes:
            allowed = ", ".join(str(k) for k in sorted(modes))
            res.flags.append(TemplateFlag(
                "TBANK_TEMPLATE_OPERATOR_COUNT",
                f"для высоты {prof_h} pt: {op}={metrics[key]}, "
                f"в корпусе допустимо: {allowed}",
            ))
            break

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        td = doc[0].get_text("dict")
        doc.close()
        spans = _label_spans(td)
        res.stats["label_spans"] = {
            k: {"x0": v["x0"], "y0": v["y0"]} for k, v in spans.items()
            if k in ("Итого", "Перевод", "Статус", "Сумма")
        }
        res.flags.extend(_check_label_coords(spans, _load_label_clusters()))
    except Exception:
        pass

    return res
