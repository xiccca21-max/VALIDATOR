"""Label–value geometry contracts for Sber v2."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import fitz
except ImportError:
    fitz = None

from ..field_edge_alignment import check_sber_label_left_edge
from .profile_gates import profile_allows_rule
from .types import SberFlag

# Per-profile required labels (geometry presence). Foreign labels → HARD.
# Values may be a string or a tuple of acceptable aliases (any match counts).
_REQUIRED_LABELS: dict[str, tuple[str | tuple[str, ...], ...]] = {
    "sbp_outgoing": (
        "сумма",
        ("получатель", "получателя", "фио получателя"),
        "номер операции в сбп",
    ),
    "sbp_request": ("сумма", "номер операции в сбп"),
    "sber_internal_jasper": (
        "сумма",
        ("получатель", "получателя", "фио получателя"),
    ),
    "sber_internal_pdfium": (
        "сумма",
        ("получатель", "получателя", "фио получателя"),
    ),
    "legacy_phone": ("сумма", "телефон"),
    "card_other_ios": ("сколько", "комиссия", "списано"),
}

# Markers of a *foreign receipt template*, not recipient bank names in SBP fields.
_FOREIGN_LABELS = (
    "квитанция тинькофф", "квитанция т-банк", "tinkoff bank",
    "квитанция о переводе по сбп альфа", "alfa-bank receipt",
    "btc wallet", "usdt", "криптокошел",
)


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True
    missing_required: list[str] = field(default_factory=list)


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "geometry") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def _span_texts(pdf_bytes: bytes) -> list[tuple[str, tuple[float, float, float, float]]]:
    if not fitz:
        return []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: list[tuple[str, tuple[float, float, float, float]]] = []
    if doc.page_count:
        page = doc[0]
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = (span.get("text") or "").strip()
                    if t:
                        bbox = tuple(span.get("bbox") or (0, 0, 0, 0))
                        out.append((t, bbox))  # type: ignore[arg-type]
    doc.close()
    return out


def _label_found(lab: str | tuple[str, ...], low: str, span_low: str) -> bool:
    aliases = lab if isinstance(lab, tuple) else (lab,)
    return any(a in low or a in span_low for a in aliases)


def _label_name(lab: str | tuple[str, ...]) -> str:
    return lab[0] if isinstance(lab, tuple) else lab


def check_label_value_geometry(
    pdf_bytes: bytes,
    text: str,
    *,
    profile_id: str,
) -> CheckResult:
    out = CheckResult()
    try:
        if not profile_allows_rule(profile_id, require_exact=True):
            out.stats["skipped"] = "profile_gate"
            return out

        low = (text or "").lower()
        for foreign in _FOREIGN_LABELS:
            if foreign in low:
                out.flags.append(_f(
                    "SBER_LABEL_VALUE_GEOMETRY_CONFLICT",
                    f"чужой field box / маркер «{foreign}» в чеке Сбер",
                ))

        required = _REQUIRED_LABELS.get(profile_id, ())
        spans = _span_texts(pdf_bytes)
        span_low = " ".join(t.lower() for t, _ in spans)
        missing = [
            _label_name(lab)
            for lab in required
            if not _label_found(lab, low, span_low)
        ]
        out.missing_required = missing
        out.stats["required"] = [_label_name(lab) for lab in required]
        out.stats["missing"] = missing

        # Geometry drift: required labels present in text but no span near page body
        if missing:
            out.flags.append(_f(
                "SBER_LAYOUT_DRIFT",
                f"отсутствуют label-якоря профиля: {', '.join(missing)}",
                tier="B",
                group="B2_layout_content",
            ))

        # card_other_ios: amount labels should appear in vertical order Сколько < Комиссия < Списано
        if profile_id == "card_other_ios" and spans:
            ys = {}
            for t, bbox in spans:
                tl = t.lower()
                for key in ("сколько", "комиссия", "списано"):
                    if key in tl and key not in ys:
                        ys[key] = bbox[1]
            if len(ys) == 3:
                if not (ys["сколько"] <= ys["комиссия"] <= ys["списано"] + 5):
                    out.flags.append(_f(
                        "SBER_LABEL_VALUE_GEOMETRY_CONFLICT",
                        f"порядок Сколько/Комиссия/Списано нарушен: {ys}",
                    ))

        # Intra-doc label left-edge constancy (relative; absolute X varies by profile).
        left_edge = check_sber_label_left_edge(pdf_bytes)
        out.stats["label_left_edge"] = left_edge.stats
        for fl in left_edge.flags:
            out.flags.append(_f(
                fl.code,
                fl.detail,
                tier="HARD",
                group="geometry",
            ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
