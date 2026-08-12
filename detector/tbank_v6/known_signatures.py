"""Known-fake signatures from v6.0 spec section 9.1 / 13."""

from __future__ import annotations

import hashlib

from ..ff2_pool import _extract_fontfile2
from ..pdf_forensics import _ttf_tables
from ..tbank_font_rebuilder import run_font_rebuilder_check
from .rules import K_FONT_002_PACKS
from .types import V6Flag


def _table_sha256(ttf: bytes, tag: bytes) -> str | None:
    entry = _ttf_tables(ttf).get(tag)
    if not entry:
        return None
    off, ln = entry
    return hashlib.sha256(ttf[off:off + ln]).hexdigest()


def check_k_font_002(pdf_bytes: bytes) -> V6Flag | None:
    """Disabled: glyf/loca pack blacklist is novelty cloning, not structure.

    Kept as a no-op so call sites stay stable. Prefer rebuild/reassembly and
    cross-layer contradictions (FontBBox, CID closure, content edits).
    """
    return None


def check_k_font_001(pdf_bytes: bytes) -> tuple[V6Flag | None, list[V6Flag]]:
    """Font rebuilder A — hard only as confirmed combination."""
    res = run_font_rebuilder_check(pdf_bytes)
    diagnostics: list[V6Flag] = []
    for f in res.flags:
        tier = "B" if f.code in (
            "FONT_GLOBAL_TABLES_FOREIGN_SUBSETTER",
            "STATIC_EDITABLE_DIGIT_SUBSET_F2",
            "KNOWN_FAKE_FONT_REBUILDER_SIGNATURE",
            "EXTRA_UNUSED_GLYPHS_F1_F2",
        ) else "A"
        diagnostics.append(V6Flag(
            code=f.code,
            detail=f.detail,
            tier=tier,
            group="B5_font_rebuilder" if tier == "B" else "font_cmap_glyph",
            rule_id="K-FONT-001" if res.is_fake else "",
        ))

    if not res.is_fake:
        return None, diagnostics

    return V6Flag(
        code="K-FONT-001",
        detail=(
            "подтверждённая комбинация font rebuilder A: "
            "F1/F2 timestamps ≈ CreationDate + PDF FontBBox ≠ TTF head bbox "
            "+ лишние digit glyph в F2"
        ),
        tier="KNOWN",
        group="known_malicious_signature",
        rule_id="K-FONT-001",
    ), diagnostics
