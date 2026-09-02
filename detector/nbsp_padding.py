"""Shared tell: extra trailing NBSP used to pad a donor content-stream length.

Genuine receipts keep at most one U+00A0 at the end of a text line
(Alfa Oracle/Quartz: exactly one on ФИО / «Сформирована» / message / op-id;
T-Bank / Sber / VTB / sparse banks: zero). SEQ match_cs=True appended 2–9
NBSPs so the rewritten field hit the donor decoded /Contents length.
"""

from __future__ import annotations

from dataclasses import dataclass

NBSP = "\u00a0"
CODE = "TEXT_TRAILING_NBSP_PADDING"
MIN_RUN = 2

_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("получатель", "ФИО"),
    ("отправитель", "ФИО"),
    ("имя плательщика", "ФИО"),
    ("сформирована", "Сформирована"),
    ("сообщение получателю", "сообщение"),
    ("сообщение", "сообщение"),
    ("номер операции", "номер операции"),
)


@dataclass(frozen=True)
class NbspHit:
    line_no: int
    count: int
    field: str
    sample: str


def trailing_nbsp_count(line: str) -> int:
    n = 0
    for ch in reversed(line or ""):
        if ch == NBSP:
            n += 1
        else:
            break
    return n


def _norm_label(line: str) -> str:
    return (line or "").replace(NBSP, " ").strip().lower()


def _field_kind(line: str, prev: str) -> str:
    for raw, kind in _FIELD_LABELS:
        if _norm_label(line).startswith(raw) or _norm_label(prev).startswith(raw):
            return kind
    return "строка"


def find_trailing_nbsp_padding(
    text: str,
    *,
    min_run: int = MIN_RUN,
) -> list[NbspHit]:
    hits: list[NbspHit] = []
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        count = trailing_nbsp_count(line)
        if count < min_run:
            continue
        prev = lines[index - 1] if index else ""
        sample = line.rstrip(NBSP)
        if len(sample) > 48:
            sample = sample[-48:]
        hits.append(NbspHit(
            line_no=index + 1,
            count=count,
            field=_field_kind(line, prev),
            sample=sample,
        ))
    return hits


def padding_detail(hits: list[NbspHit]) -> str:
    shown = hits[:3]
    bits = [
        f"{hit.field} ×{hit.count} NBSP (стр. {hit.line_no}, {hit.sample!r})"
        for hit in shown
    ]
    extra = f" и ещё {len(hits) - 3}" if len(hits) > 3 else ""
    return (
        "хвостовой NBSP-padding в текстовом слое: "
        + "; ".join(bits)
        + extra
        + " — подгонка длины content stream (у оригиналов 0 или 1 NBSP)"
    )
