"""T-TBANK-TEXT-LAYOUT-FINGERPRINT-001 — Jasper/OpenPDF layout."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .font_layers import _font_objects
from .structure import content_stream_bytes, is_content_stream, find_streams
from .tbank_sbp_geometry import _parse_content_runs

try:
    import fitz
except ImportError:
    fitz = None

RULE_ID = "T-TBANK-TEXT-LAYOUT-FINGERPRINT-001"
HARD_CODE = "TBANK_TEXT_LAYOUT_FINGERPRINT"
GROUP = "content_grammar_layout"

_TOLERANCE_ROUND_PT = 0.05
_TOLERANCE_HARD_PT = 0.05
_TOLERANCE_AMOUNT_PT = 1.0
_TOLERANCE_DUAL_PT = 0.15
_TARGET_RIGHT_PT = 250.0
_CROPBOX_RIGHT_DEFAULT = 280.0

_PROFILE_LABELS = (
    "итого", "сумма", "статус", "отправитель", "получатель",
    "телефон", "банк", "счет", "счёт", "идентификатор", "сбп", "квитанция",
)

_RIGHT_VALUE_RE = re.compile(
    r"^[\d\s.,₽руб+\-()A-Za-zА-Яа-яЁё*]+$",
    re.I,
)
_F1_AMOUNT_DIGITS_RE = re.compile(r"^[\d\s\u00a0\u202f]+$")


@dataclass
class LayoutLine:
    text: str
    field: str
    x: float
    y: float
    end_x: float
    font: str
    font_size: float
    width: float
    fitz_end_x: float = 0.0
    fitz_text: str = ""
    deviation: float = 0.0
    confirmed: bool = False


@dataclass
class LayoutFingerprintResult:
    hard_flags: list[tuple[str, str]] = field(default_factory=list)
    supporting_flags: list[tuple[str, str]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    lines: list[LayoutLine] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _field_kind(text: str) -> str:
    low = _norm(text)
    for key in _PROFILE_LABELS:
        if key in low:
            return key
    return ""


def _is_f1_amount_digits(text: str) -> bool:
    """F1 duplicate amount row (digits only) — originals shortfall, fakes often overflow past R."""
    s = (text or "").strip()
    if not s or not re.search(r"\d", s):
        return False
    return bool(_F1_AMOUNT_DIGITS_RE.fullmatch(s))


def _fitz_text_lines(pdf_bytes: bytes) -> list[dict]:
    """Secondary parser — full visible lines with bbox (not compact-key map)."""
    out: list[dict] = []
    if not fitz:
        return out
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_dict = doc[0].get_text("dict") if doc.page_count else {}
        doc.close()
    except Exception:
        return out
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()
            if not txt or txt.endswith(":"):
                continue
            bbox = line.get("bbox") or (0, 0, 0, 0)
            xs = [sp["bbox"][2] for sp in line.get("spans", []) if sp.get("bbox")]
            if xs:
                out.append({
                    "text": txt,
                    "compact": re.sub(r"\s+", "", txt),
                    "y": float(bbox[1]),
                    "end_x": max(xs),
                })
    return out


def _match_fitz_line(run: dict, fitz_lines: list[dict]) -> dict | None:
    compact = re.sub(r"\s+", "", run.get("text") or "")
    if not compact:
        return None
    best: dict | None = None
    best_score = 999.0
    for fl in fitz_lines:
        if abs(fl["y"] - run["y"]) > 2.5:
            continue
        ft = fl["compact"]
        if compact == ft or compact in ft or ft in compact:
            score = abs(fl["y"] - run["y"])
            if score < best_score:
                best = fl
                best_score = score
    return best


def _cropbox_right(pdf_bytes: bytes) -> float:
    m = re.search(rb"/CropBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s*\]", pdf_bytes[:8000])
    if m:
        return float(m.group(1))
    m = re.search(rb"/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s*\]", pdf_bytes[:8000])
    if m:
        return float(m.group(1))
    return _CROPBOX_RIGHT_DEFAULT


def _combine_amount_ruble(runs: list[dict]) -> list[dict]:
    out: list[dict] = []
    used: set[int] = set()
    for i, r in enumerate(runs):
        if i in used:
            continue
        if r["font"] == "F2" and r["x"] > 100:
            combined = dict(r)
            for j, r2 in enumerate(runs):
                if j == i or j in used:
                    continue
                if r2["font"] == "F3" and abs(r2["y"] - r["y"]) < 1.0 and r2["x"] >= r["end_x"] - 1.0:
                    combined["text"] = (r["text"] + r2["text"]).strip()
                    combined["width"] = r2["end_x"] - r["x"]
                    combined["end_x"] = r2["end_x"]
                    used.add(j)
                    break
            out.append(combined)
            used.add(i)
        elif i not in used:
            out.append(r)
            used.add(i)
    return out


def _right_boundary_f1(runs: list[dict]) -> float:
    edges: list[float] = []
    for r in runs:
        if r["x"] < 100 or r["font"] != "F1":
            continue
        if not (8.0 <= r["font_size"] <= 10.0):
            continue
        if not r["text"] or r["text"].endswith(":"):
            continue
        compact = r["text"].replace(" ", "")
        if not _RIGHT_VALUE_RE.match(compact):
            continue
        if 235.0 <= r["end_x"] <= 265.0:
            edges.append(r["end_x"])
    if not edges:
        return _TARGET_RIGHT_PT
    near = [e for e in edges if abs(e - _TARGET_RIGHT_PT) <= 0.5]
    if len(near) >= 3:
        return statistics.median(near)
    return statistics.median(edges)


def _boxes_overlap(a: dict, b: dict) -> bool:
    if abs(a["y"] - b["y"]) > 1.5:
        return False
    return not (a["end_x"] <= b["x"] + _TOLERANCE_ROUND_PT or b["end_x"] <= a["x"] + _TOLERANCE_ROUND_PT)


def check_tbank_layout_fingerprint(
    pdf_bytes: bytes,
    text: str = "",
    *,
    shadow: bool = False,
    regression_passed: bool = True,
) -> LayoutFingerprintResult:
    """
    Raw /W + Tm + CID widths (/DW fallback); fitz as independent second parser.
    HARD only when both parsers agree on overflow AND overlap/crop/page violation exists.
    """
    res = LayoutFingerprintResult()
    content = content_stream_bytes(pdf_bytes)
    if not content:
        for _, dec in find_streams(pdf_bytes):
            if dec and is_content_stream(dec):
                content = dec
                break
    if not content:
        res.stats["skipped"] = "no_content_stream"
        return res

    fonts_meta = _font_objects(pdf_bytes)
    fonts = fonts_meta[0] if isinstance(fonts_meta, tuple) else fonts_meta
    runs = _combine_amount_ruble(_parse_content_runs(content, fonts))
    if not runs:
        res.stats["skipped"] = "no_runs"
        return res

    fitz_lines = _fitz_text_lines(pdf_bytes)
    right_r = _right_boundary_f1(runs)
    crop_r = _cropbox_right(pdf_bytes)
    res.stats["right_boundary"] = round(right_r, 3)
    res.stats["cropbox_right"] = round(crop_r, 3)
    res.stats["run_count"] = len(runs)

    value_runs = [
        r for r in runs
        if r["x"] >= 100 and r["font"] == "F1" and r["text"] and not r["text"].endswith(":")
    ]
    amount_runs = [
        r for r in runs
        if r["x"] >= 100 and r.get("font") == "F2" and r["text"] and re.search(r"\d", r["text"])
    ]

    hard_candidates: list[tuple[str, str]] = []
    supporting_candidates: list[tuple[str, str]] = []
    diag_notes: list[str] = []

    def _check_run(r: dict, *, amount: bool = False, f1_amount: bool = False) -> None:
        fl = _match_fitz_line(r, fitz_lines)
        fitz_end = fl["end_x"] if fl else 0.0
        fitz_text = fl["text"] if fl else ""
        label = fitz_text or r["text"]
        overflow = r["end_x"] - right_r
        shortfall = right_r - r["end_x"]
        deviation = abs(overflow) if overflow > 0 else abs(shortfall)

        fitz_overflow = (fitz_end - right_r) if fitz_end else 0.0
        dual_agree = (
            fitz_end > 0
            and abs(fitz_end - r["end_x"]) <= _TOLERANCE_DUAL_PT
            and overflow > _TOLERANCE_HARD_PT
            and fitz_overflow > _TOLERANCE_HARD_PT
        )
        fitz_confirms_overflow = fitz_end > 0 and fitz_overflow > _TOLERANCE_HARD_PT
        crop_violation = r["end_x"] > crop_r + _TOLERANCE_HARD_PT
        pool = value_runs if not amount else amount_runs
        intersects = any(
            _boxes_overlap(r, other)
            for other in pool
            if other is not r and other["y"] != r["y"]
        )
        amount_overflow = (amount or f1_amount) and overflow > _TOLERANCE_AMOUNT_PT
        structural = crop_violation or intersects

        ln = LayoutLine(
            text=label,
            field="сумма" if (amount or f1_amount) else _field_kind(label),
            x=r["x"],
            y=r["y"],
            end_x=round(r["end_x"], 3),
            font=r["font"],
            font_size=r["font_size"],
            width=round(r["width"], 3),
            fitz_end_x=round(fitz_end, 3) if fitz_end else 0.0,
            fitz_text=fitz_text,
            deviation=round(deviation, 3),
            confirmed=dual_agree,
        )
        res.lines.append(ln)

        if deviation <= _TOLERANCE_ROUND_PT:
            diag_notes.append(
                f"[diagnostic] {RULE_ID}: «{label}» delta={deviation:.3f}pt (округление)"
            )
            return

        if overflow <= _TOLERANCE_HARD_PT:
            if shortfall > 0.5 and r["x"] > 150:
                diag_notes.append(
                    f"[diagnostic] {RULE_ID}: «{label}» shortfall {shortfall:.3f}pt от R={right_r:.2f}"
                )
            return

        detail = (
            f"{'сумма' if amount else 'строка'} «{label}» raw end_x={r['end_x']:.3f}, "
            f"R={right_r:.3f}, overflow={overflow:.3f}pt"
            + (f"; fitz_end={fitz_end:.3f}" if fitz_end else "")
            + ("; dual" if dual_agree else "")
            + ("; cropbox" if crop_violation else "")
            + ("; intersection" if intersects else "")
        )

        if (dual_agree or (amount_overflow and fitz_confirms_overflow)) and structural:
            hard_candidates.append((HARD_CODE, detail))
        elif f1_amount and amount_overflow:
            hard_candidates.append((HARD_CODE, detail + "; F1 amount column overflow"))
        elif amount_overflow or fitz_confirms_overflow or dual_agree:
            supporting_candidates.append((HARD_CODE, detail))
        else:
            diag_notes.append(
                f"[diagnostic] {RULE_ID}: «{label}» raw overflow {overflow:.3f}pt "
                f"без dual-подтверждения и без overlap/crop"
            )

    for r in value_runs:
        if _is_f1_amount_digits(r["text"]) and r["x"] >= 150:
            _check_run(r, amount=False, f1_amount=True)
        else:
            _check_run(r, amount=False)
    for r in amount_runs:
        _check_run(r, amount=True)

    res.diagnostics.extend(diag_notes[:20])
    res.stats["hard_candidates"] = len(hard_candidates)
    res.stats["supporting_candidates"] = len(supporting_candidates)
    res.stats["mode"] = "active" if not shadow else "shadow"

    if not shadow or regression_passed:
        res.hard_flags.extend(hard_candidates)
        res.supporting_flags.extend(supporting_candidates)

    return res
