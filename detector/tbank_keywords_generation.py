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

# Jasper IB/Receipt switched the /Keywords third token on 10.07.2026.
# Live originals after that date carry «DOCS-2035» (Receipt.pdf, 18.08.2026).
# Treating DOCS-2035 as always-fake was a corpus-cutoff error: the older
# n=128 sample ended before the bank switch.
TRANSITION_DATETIME = datetime.datetime(2026, 7, 10, 0, 0, 0)
OLD_TAIL = "991"
NEW_TAIL = "DOCS-2035"
NATIVE_TAIL = OLD_TAIL
FOREIGN_TAIL = NEW_TAIL


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


def _expected_tail(when: datetime.datetime) -> str:
    return NEW_TAIL if when >= TRANSITION_DATETIME else OLD_TAIL


def check_keywords_generation(
    pdf_bytes: bytes,
    *,
    creation_date: str = "",
    printed_datetime: datetime.datetime | None = None,
) -> KeywordsGenerationResult:
    """
    Для /reports/IB/Receipt:
    - до 10.07.2026 third token «991»;
    - с 10.07.2026 third token «DOCS-2035»;
    - токен обязан совпасть и с /CreationDate|/Keywords date, и с
      напечатанной датой операции: SEQ поднимает Keywords на 11.08 +
      DOCS-2035, оставляя лицо 28.05 (10_my.pdf). На 270 Jasper-оригиналах
      пары «операция до 10.07 + DOCS-2035» нет;
    - смешанная пара любая дата↔токен → HARD;
    - прочие хвосты и неизвестная дата при штатном токене — telemetry.
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

    if printed_datetime is not None:
        out.stats["printed_at"] = printed_datetime.isoformat(sep=" ")
        out.stats["printed_after_transition"] = (
            printed_datetime >= TRANSITION_DATETIME
        )

    is_old = out.tail == OLD_TAIL or out.tail.endswith(OLD_TAIL)
    is_new = out.tail == NEW_TAIL or out.tail.endswith(NEW_TAIL)
    if not is_old and not is_new:
        out.stats["generation"] = "unknown_tail"
        return out

    got = NEW_TAIL if is_new else OLD_TAIL
    mismatches: list[str] = []
    expected_formed = ""
    expected_printed = ""

    if formed is not None:
        expected_formed = _expected_tail(formed)
        if got != expected_formed:
            mismatches.append(
                f"даты /Keywords|/CreationDate {formed.strftime('%d.%m.%Y')}"
            )

    if printed_datetime is not None:
        expected_printed = _expected_tail(printed_datetime)
        if got != expected_printed:
            mismatches.append(
                f"напечатанной даты операции "
                f"{printed_datetime.strftime('%d.%m.%Y')}"
            )

    if not mismatches:
        out.stats["generation"] = "native_ok"
        return out

    out.mismatch = True
    out.stats["generation"] = "date_token_mismatch"
    if expected_formed:
        out.stats["expected_tail"] = expected_formed
    if expected_printed:
        out.stats["expected_printed_tail"] = expected_printed
    out.detail = (
        f"/Keywords third token «{out.tail}» не совпадает с поколением "
        f"{' и '.join(mismatches)}: до 10.07.2026 ожидается "
        f"«{OLD_TAIL}», с 10.07.2026 — «{NEW_TAIL}»"
    )
    return out
