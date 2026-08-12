"""Overlay / hidden text-layer checks for Sber v2."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import fitz
except ImportError:
    fitz = None

from .types import SberFlag


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD") -> SberFlag:
    return SberFlag(
        code=code, detail=detail, tier=tier, group="visibility", rule_id=code,
    )


def check_overlay_hidden_text(pdf_bytes: bytes) -> CheckResult:
    """Tr3 / zero size / off-page / white-on-white / clip overlay."""
    out = CheckResult()
    if not fitz:
        out.analysis_ok = False
        out.stats["error"] = "fitz_missing"
        return out
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not doc.page_count:
            doc.close()
            return out
        page = doc[0]
        rect = page.rect
        hidden = 0
        samples = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text or len(text) < 2:
                        continue
                    size = float(span.get("size") or 0)
                    bbox = span.get("bbox") or (0, 0, 0, 0)
                    x0, y0, x1, y1 = bbox
                    color = span.get("color")
                    # Tr rendering mode not always exposed; use size/off-page/alpha proxies
                    off_page = (
                        x1 < rect.x0 - 2 or y1 < rect.y0 - 2
                        or x0 > rect.x1 + 2 or y0 > rect.y1 + 2
                    )
                    zero = size < 0.3 or (abs(x1 - x0) < 0.3 and abs(y1 - y0) < 0.3)
                    white = color in (16777215, 0xFFFFFF) and len(text) >= 4
                    if off_page or zero:
                        hidden += 1
                        samples.append(f"{text[:24]!r} size={size:.2f} off={off_page}")
                    elif white and any(ch.isdigit() for ch in text):
                        # white digit runs are suspicious overlays
                        hidden += 1
                        samples.append(f"white«{text[:24]}»")
        doc.close()
        out.stats["hidden_spans"] = hidden
        if hidden >= 3:
            out.flags.append(_f(
                "SBER_OVERLAY_HIDDEN_TEXT_LAYER",
                f"скрытый/off-page текстовый слой ({hidden}): {'; '.join(samples[:3])}",
            ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
