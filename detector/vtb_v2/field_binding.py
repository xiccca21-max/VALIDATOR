"""VTB label/value row binding — catch a foreign-bank shell with SBP coords.

Broken donors (Alfa SBP painted into a VTB openhtml page) put the date on
the amount row and ФИО on the operation-id row. Presence of labels alone
is not enough: the *next* line must be the expected type. Two mismatches
are required so a single extraction quirk cannot decide.
"""

from __future__ import annotations

import re

from .types import VtbFlag

_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_MONEY_RE = re.compile(
    r"\d[\d\s\u00a0\u202f]*\s*(?:₽|руб)",
    re.IGNORECASE,
)
_SBP_HEAD_RE = re.compile(r"^[AB][0-9A-Z]{10,}$")
_SBP_TAIL_RE = re.compile(r"^\d{4,8}$")
_NAME_RE = re.compile(r"[А-ЯЁа-яёA-Za-z]{2,}")


def _flag(code: str, detail: str) -> VtbFlag:
    return VtbFlag(code=code, detail=detail, tier="HARD", group="fields", rule_id=code)


def _next_value(lines: list[str], index: int) -> str:
    inline = lines[index].split(":", 1)
    if len(inline) == 2 and inline[1].strip():
        return inline[1].strip()
    if index + 1 < len(lines):
        return lines[index + 1]
    return ""


def _is_date(value: str) -> bool:
    return bool(_DATE_RE.search(value or ""))


def _is_money(value: str) -> bool:
    return bool(_MONEY_RE.search(value or "")) and not _is_date(value)


def _is_sbp_id(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "")
    return bool(_SBP_HEAD_RE.match(compact) or _SBP_TAIL_RE.match(compact))


def _is_name(value: str) -> bool:
    if _is_date(value) or _is_money(value) or _is_sbp_id(value):
        return False
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 10:
        return False
    return bool(_NAME_RE.search(value or ""))


def check_field_value_binding(text: str) -> list[VtbFlag]:
    lines = [
        line.replace("\xa0", " ").replace("\u202f", " ").strip()
        for line in (text or "").splitlines()
        if line.strip()
    ]
    checks = (
        (
            ("дата операции",),
            "дата",
            _is_date,
        ),
        (
            ("сумма операции", "сумма зачисления"),
            "сумма",
            _is_money,
        ),
        (
            ("id операции в сбп", "id операции"),
            "идентификатор СБП",
            _is_sbp_id,
        ),
        (
            ("получатель", "имя плательщика", "отправитель"),
            "ФИО",
            _is_name,
        ),
    )
    mismatches: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        low = line.lower()
        for labels, expected, predicate in checks:
            if not any(low == label or low.startswith(label) for label in labels):
                continue
            value = _next_value(lines, index)
            if value and not predicate(value):
                mismatches.append({
                    "label": line,
                    "value": value,
                    "expected": expected,
                })
            break

    if len(mismatches) < 2:
        return []
    detail = "; ".join(
        f"{item['label']!r} → {item['value']!r}, ожидалось: {item['expected']}"
        for item in mismatches
    )
    return [_flag(
        "VTB_FIELD_VALUE_BINDING_CONFLICT",
        "значения сдвинуты относительно подписей полей: " + detail,
    )]
