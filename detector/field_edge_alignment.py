"""Intra-document field-edge constancy (bank layout contracts).

Banks keep either a shared value-column *right* edge (T-Bank, PSB, …)
or a shared label *left* edge (Sber, VTB, Ozon, …).

Policy: HARD only on *relative* spread inside one PDF — never on an absolute
atlas X. A future genuine that shifts the whole column (e.g. R=250→255) stays
clean; a reassembly that misaligns fields in the same receipt does not.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

try:
    import fitz
except ImportError:
    fitz = None

# OpenPDF F1 value-column: genuines ≤1.41 pt spread; leave margin for future.
_TBANK_RIGHT_SPREAD_HARD = 2.0
_TBANK_RIGHT_MIN_FIELDS = 4
_TBANK_RIGHT_CLUSTER_BAND = 5.0

# Jasper IB/Receipt pins the value column to R≈250 pt. Genuines never overshoot
# past +0.007 pt (n=128); SEQ footer amount/ruble often lands at +0.15+.
# Absolute pin is intentional here — relative spread alone misses a single
# drifted footer when the rest of the column stays tight.
_TBANK_RIGHT_PIN_PT = 250.0
# Genuines ≤0.005 pt (n=128); SEQ phone residual often lands at +0.015…0.02.
_TBANK_RIGHT_OVERSHOOT_HARD = 0.01
_TBANK_RIGHT_RESIDUAL_QUANT = 0.05
# Card/phone MediaBox heights: residual lattice is exactly {-1.0, 0.0}.
# SBP shells (h≥519) may carry rare −0.65/−1.4 genuines — lattice not applied.
_TBANK_RIGHT_LATTICE = frozenset({-1.0, 0.0})
_TBANK_RIGHT_LATTICE_MAX_HEIGHT = 499.0

# Sber labels: genuines span 0.0 within a receipt; absolute X varies (19/21/32…).
_SBER_LEFT_SPREAD_HARD = 1.0
_SBER_LEFT_MIN_LABELS = 3
_SBER_LEFT_CLUSTER_BAND = 3.0

_SBER_LABELS = frozenset({
    "сумма", "комиссия", "получатель", "плательщик", "телефон",
    "номер операции в сбп", "фио получателя", "списано", "сколько",
    "дата", "статус", "отправитель", "банк получателя", "счёт", "счет",
})


@dataclass
class EdgeFlag:
    code: str
    detail: str
    tier: str = "A"
    group: str = "B4_text_layout"
    rule_id: str = ""


@dataclass
class EdgeCheckResult:
    flags: list[EdgeFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _cluster_spread(values: list[float], *, band: float) -> tuple[float, float, int] | None:
    """Return (median, span, n_cluster) for the main cluster around the median."""
    if len(values) < 2:
        return None
    ordered = sorted(values)
    med = ordered[len(ordered) // 2]
    cluster = [v for v in ordered if abs(v - med) <= band]
    if len(cluster) < 2:
        return None
    return med, max(cluster) - min(cluster), len(cluster)


def _fitz_spans(pdf_bytes: bytes) -> list[tuple[str, float, float, float, float]]:
    if not fitz:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not doc.page_count:
            doc.close()
            return []
        page = doc[0]
        out: list[tuple[str, float, float, float, float]] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    out.append((text, float(x0), float(x1), float(y0), float(y1)))
        doc.close()
        return out
    except Exception:
        return []


def _tbank_value_column_line_edges(
    pdf_bytes: bytes,
) -> tuple[list[float], float | None]:
    """Line-level value-column right edges (x0≥100, x1≥180) + page height.

    Matches placement_residual_vector field selection — amount+ruble share one
    line bbox, so footer «3 500 ₽» overshoot is visible as a single x1.
    """
    if not fitz:
        return [], None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not doc.page_count:
            doc.close()
            return [], None
        page = doc[0]
        height = float(page.rect.height)
        d = page.get_text("dict")
        doc.close()
    except Exception:
        return [], None

    ends: list[float] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            if not spans:
                continue
            txt = "".join(sp.get("text", "") for sp in spans).strip()
            if not txt or len(txt) < 2:
                continue
            boxes = [sp["bbox"] for sp in spans if sp.get("bbox")]
            if not boxes:
                continue
            x0 = min(float(b[0]) for b in boxes)
            x1 = max(float(b[2]) for b in boxes)
            if x0 < 100 or x1 < 180:
                continue
            ends.append(x1)
    return ends, height


def check_tbank_value_right_edge(pdf_bytes: bytes) -> EdgeCheckResult:
    """T-Bank / Jasper: F1 value-column right edges must share one vertical."""
    from .font_layers import _font_objects
    from .structure import content_stream_bytes, find_streams, is_content_stream
    from .tbank_sbp_geometry import _parse_content_runs
    from .tbank_text_layout_fingerprint import _RIGHT_VALUE_RE, _combine_amount_ruble

    out = EdgeCheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        out.stats["skipped"] = "not_openpdf"
        return out

    content = content_stream_bytes(pdf_bytes)
    if not content:
        for _, dec in find_streams(pdf_bytes):
            if dec and is_content_stream(dec):
                content = dec
                break
    if not content:
        out.stats["skipped"] = "no_content"
        return out

    fonts_meta = _font_objects(pdf_bytes)
    fonts = fonts_meta[0] if isinstance(fonts_meta, tuple) else fonts_meta
    runs = _combine_amount_ruble(_parse_content_runs(content, fonts))
    ends: list[float] = []
    for run in runs:
        if run.get("font") != "F1" or run.get("x", 0) < 100:
            continue
        if not (8.0 <= float(run.get("font_size") or 0) <= 10.0):
            continue
        text = run.get("text") or ""
        if not text or text.endswith(":"):
            continue
        if not _RIGHT_VALUE_RE.match(text.replace(" ", "")):
            continue
        ends.append(float(run["end_x"]))

    out.stats["value_right_edges"] = [round(e, 3) for e in ends]
    out.stats["value_right_n"] = len(ends)
    clustered = _cluster_spread(ends, band=_TBANK_RIGHT_CLUSTER_BAND)
    if clustered:
        med, span, n_cluster = clustered
        out.stats["value_right_median"] = round(med, 3)
        out.stats["value_right_spread"] = round(span, 3)
        out.stats["value_right_cluster_n"] = n_cluster

        # Relative only — do not pin median≈250 (future column shift stays clean).
        if n_cluster >= _TBANK_RIGHT_MIN_FIELDS and span > _TBANK_RIGHT_SPREAD_HARD:
            out.flags.append(EdgeFlag(
                code="TBANK_VALUE_RIGHT_EDGE_SPREAD",
                detail=(
                    f"правые края value-колонки F1 разъехались на {span:.2f} pt "
                    f"(n={n_cluster}, median={med:.1f}; HARD>{_TBANK_RIGHT_SPREAD_HARD}) — "
                    f"у Jasper/OpenPDF значения сидят на одной вертикали"
                ),
                rule_id="TBANK_VALUE_RIGHT_EDGE_SPREAD",
            ))

    # Absolute R≈250 pin: overshoot + card-height residual lattice.
    line_ends, page_h = _tbank_value_column_line_edges(pdf_bytes)
    out.stats["value_column_line_edges"] = [round(e, 3) for e in line_ends]
    out.stats["value_column_page_h"] = page_h
    if line_ends:
        residuals = [e - _TBANK_RIGHT_PIN_PT for e in line_ends]
        max_over = max(residuals)
        out.stats["value_column_max_overshoot"] = round(max_over, 4)
        q_residuals = [
            round(round(r / _TBANK_RIGHT_RESIDUAL_QUANT) * _TBANK_RIGHT_RESIDUAL_QUANT, 2)
            for r in residuals
        ]
        out.stats["value_column_residuals_q"] = sorted(q_residuals)
        if max_over > _TBANK_RIGHT_OVERSHOOT_HARD:
            out.flags.append(EdgeFlag(
                code="TBANK_VALUE_RIGHT_EDGE_OVERSHOOT",
                detail=(
                    f"value-колонка вылезла за R={_TBANK_RIGHT_PIN_PT:g} на "
                    f"+{max_over:.3f} pt (HARD>+{_TBANK_RIGHT_OVERSHOOT_HARD:g}; "
                    f"у Jasper/OpenPDF max overshoot ≤0.005 на n=128) — "
                    f"SEQ сдвинул footer amount/₽ вправо"
                ),
                rule_id="TBANK_VALUE_RIGHT_EDGE_OVERSHOOT",
            ))
        if (
            page_h is not None
            and page_h <= _TBANK_RIGHT_LATTICE_MAX_HEIGHT
            and len(q_residuals) >= 4
        ):
            off = sorted({q for q in q_residuals if q not in _TBANK_RIGHT_LATTICE})
            out.stats["value_column_off_lattice"] = off
            if off:
                out.flags.append(EdgeFlag(
                    code="TBANK_VALUE_RIGHT_EDGE_OFF_LATTICE",
                    detail=(
                        f"value-колонка residual∉{{-1.0,0.0}} при height={page_h:g}: "
                        f"{off} (квант {_TBANK_RIGHT_RESIDUAL_QUANT:g} pt) — "
                        f"у card/phone Jasper residual lattice ровно {{-1,0}}"
                    ),
                    rule_id="TBANK_VALUE_RIGHT_EDGE_OFF_LATTICE",
                ))
    return out


def check_sber_label_left_edge(pdf_bytes: bytes) -> EdgeCheckResult:
    """Sber: required labels share one left edge inside the receipt."""
    out = EdgeCheckResult()
    spans = _fitz_spans(pdf_bytes)
    lefts: list[float] = []
    for text, x0, _x1, _y0, _y1 in spans:
        low = text.casefold()
        if low in _SBER_LABELS or any(low.startswith(lab) for lab in _SBER_LABELS):
            lefts.append(x0)

    out.stats["label_left_edges"] = [round(x, 3) for x in lefts]
    out.stats["label_left_n"] = len(lefts)
    clustered = _cluster_spread(lefts, band=_SBER_LEFT_CLUSTER_BAND)
    if not clustered:
        return out
    med, span, n_cluster = clustered
    out.stats["label_left_median"] = round(med, 3)
    out.stats["label_left_spread"] = round(span, 3)
    out.stats["label_left_cluster_n"] = n_cluster

    # Absolute X differs across Sber profiles (19/21/32) — only relative spread.
    if n_cluster >= _SBER_LEFT_MIN_LABELS and span > _SBER_LEFT_SPREAD_HARD:
        out.flags.append(EdgeFlag(
            code="SBER_LABEL_LEFT_EDGE_SPREAD",
            detail=(
                f"левые края подписей разъехались на {span:.2f} pt "
                f"(n={n_cluster}, median={med:.1f}; HARD>{_SBER_LEFT_SPREAD_HARD}) — "
                f"у Сбера labels на одной вертикали"
            ),
            rule_id="SBER_LABEL_LEFT_EDGE_SPREAD",
        ))
    return out


def check_generic_label_left_edge(
    pdf_bytes: bytes,
    *,
    labels: frozenset[str],
    code: str,
    bank_name: str,
    hard_spread: float = 1.0,
    min_labels: int = 3,
) -> EdgeCheckResult:
    """Shared left-edge constancy for left-aligned banks (VTB/Ozon/…)."""
    out = EdgeCheckResult()
    lefts: list[float] = []
    for text, x0, _x1, _y0, _y1 in _fitz_spans(pdf_bytes):
        low = text.casefold()
        if low in labels or any(low.startswith(lab) for lab in labels):
            lefts.append(x0)
    out.stats["label_left_n"] = len(lefts)
    clustered = _cluster_spread(lefts, band=3.0)
    if not clustered:
        return out
    med, span, n_cluster = clustered
    out.stats["label_left_median"] = round(med, 3)
    out.stats["label_left_spread"] = round(span, 3)
    if n_cluster >= min_labels and span > hard_spread:
        out.flags.append(EdgeFlag(
            code=code,
            detail=(
                f"левые края подписей {bank_name} разъехались на {span:.2f} pt "
                f"(n={n_cluster}, median={med:.1f}; HARD>{hard_spread})"
            ),
            rule_id=code,
        ))
    return out
