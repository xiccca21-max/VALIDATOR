"""K-TBANK-KEYWORDS-GENERATION-001 — /Keywords generation profile (IB/Receipt)."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

_KEYWORDS_RE = re.compile(rb"/Keywords\s*\(((?:[^()\\]|\\.)*)\)")
_SUBJECT_MARKERS = (b"/reports/IB/Receipt", b"IB/Receipt")
_KW_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
_PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
)

# SEQ/forger generation token. Native Jasper IB/Receipt genuines (чеки/т банк,
# n=128) always use third-token «991»; DOCS-2035 appears only on confirmed fakes
# (serializer families + CLEAN-miss SBP shells). The prior "bank switched on
# 10.07.2026" story was poisoned by SEQ metadata — no genuine after that date
# carries DOCS-2035.
TRANSITION_DATETIME = datetime.datetime(2026, 7, 10, 0, 0, 0)  # retained for stats
NATIVE_TAIL = "991"
FOREIGN_TAIL = "DOCS-2035"
# Back-compat aliases used by serializer-family conjunctions.
OLD_TAIL = NATIVE_TAIL
NEW_TAIL = FOREIGN_TAIL


@dataclass
class KeywordsGenerationResult:
    applies: bool = False
    mismatch: bool = False
    tail: str = ""
    keywords_raw: str = ""
    formed_at: str = ""
    after_transition: bool = False
    detail: str = ""
    stats: dict = field(default_factory=dict)


def _parse_kw_date(value: str) -> datetime.datetime | None:
    m = _KW_DATE_RE.search(value or "")
    if not m:
        return None
    try:
        d, mo, y, h, mi, s = map(int, m.groups())
        return datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _parse_pdf_meta_date(value: str) -> datetime.datetime | None:
    if not value:
        return None
    m = _PDF_DATE_RE.search(value)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = map(int, m.groups())
        return datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _keywords_raw(pdf_bytes: bytes) -> str:
    m = _KEYWORDS_RE.search(pdf_bytes)
    if not m:
        return ""
    return m.group(1).decode("latin1", "replace").strip()


def _is_ib_receipt_profile(pdf_bytes: bytes) -> bool:
    return any(marker in pdf_bytes for marker in _SUBJECT_MARKERS)


def _keywords_tail(keywords: str) -> str:
    parts = [p.strip() for p in (keywords or "").split("|")]
    return parts[-1] if parts else ""


def check_keywords_generation(
    pdf_bytes: bytes,
    *,
    creation_date: str = "",
) -> KeywordsGenerationResult:
    """
    Для /reports/IB/Receipt:
    - third token «991» — штатный Jasper/OpenPDF (0 FP на корпусе оригиналов);
    - «DOCS-2035» — чужой generation token SEQ/serializer families → HARD;
    - прочие хвосты — telemetry only (не novelty-atlas whitelist).
    """
    out = KeywordsGenerationResult()
    if not _is_ib_receipt_profile(pdf_bytes):
        out.stats["skipped"] = "not_ib_receipt_profile"
        return out

    out.applies = True
    kw = _keywords_raw(pdf_bytes)
    out.keywords_raw = kw
    if not kw:
        out.stats["missing"] = True
        return out

    out.tail = _keywords_tail(kw)
    out.stats["tail"] = out.tail

    formed = _parse_pdf_meta_date(creation_date)
    if not formed:
        formed = _parse_kw_date(kw.split("|")[0].strip())
    if formed:
        out.formed_at = formed.isoformat(sep=" ")
        out.after_transition = formed >= TRANSITION_DATETIME
        out.stats["formed_at"] = out.formed_at
        out.stats["after_transition"] = out.after_transition

    if out.tail == FOREIGN_TAIL or out.tail.endswith(FOREIGN_TAIL):
        out.mismatch = True
        out.detail = (
            f"/Keywords third token «{out.tail}» — чужой generation marker "
            f"(SEQ/serializer); у нативных Jasper IB/Receipt оригинал всегда "
            f"«{NATIVE_TAIL}», токен «{FOREIGN_TAIL}» в корпусе оригиналов "
            f"не встречается"
        )
        out.stats["generation"] = "foreign_docs2035"
        return out

    if out.tail == NATIVE_TAIL or out.tail.endswith(NATIVE_TAIL):
        out.stats["generation"] = "native_ok"
        return out

    out.stats["generation"] = "unknown_tail"
    return out
