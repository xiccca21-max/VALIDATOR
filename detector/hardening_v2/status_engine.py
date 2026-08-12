"""Status engine — G-STATUS-001/002/003."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .bank_contracts import status_optional

_SUCCESS = (
    "успешно", "выполнено", "исполнено", "обработано", "проведено", "проведён",
    "завершено", "операция выполнена", "перевод выполнен", "исполнен",
)
_PENDING = (
    "ожидает", "в обработке", "обрабатывается", "на рассмотрении", "ожидание",
    "ожидает подтверждения", "не заверш", "pending",
)
_FAILED = (
    "отклонено", "отклонен", "отклонён", "неуспеш", "не выполнен", "ошибка",
    "отменено", "отменен", "отменён", "failed", "rejected",
)

_STATUS_LABEL_RE = re.compile(
    r"(?:статус(?:\s+операции)?|состояние(?:\s+операции)?)\s*[:\s]+(.{2,80})",
    re.I,
)


@dataclass
class StatusResult:
    primary_class: str = "UNKNOWN_STATUS"
    primary_text: str = ""
    all_statuses: list[tuple[str, str]] = field(default_factory=list)
    conflict: bool = False
    conflict_detail: str = ""
    user_warning: str = ""
    stats: dict = field(default_factory=dict)


def _classify_one(text: str) -> str:
    low = (text or "").lower().strip()
    if not low:
        return "UNKNOWN_STATUS"
    if any(w in low for w in _FAILED):
        return "FAILED_FINAL"
    if any(w in low for w in _PENDING):
        return "PENDING_NONFINAL"
    if any(w in low for w in _SUCCESS):
        return "SUCCESS_FINAL"
    return "UNKNOWN_STATUS"


def _extract_status_phrases(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    t = text or ""
    for m in _STATUS_LABEL_RE.finditer(t):
        phrase = m.group(1).strip().split("\n")[0].strip()
        if phrase:
            out.append(("field", phrase))
    low = t.lower()
    for phrase in (
        "операция выполнена", "перевод выполнен", "исполнено", "исполнен",
        "ожидает подтверждения", "в обработке", "отклонено", "неуспешно",
    ):
        if phrase in low:
            out.append(("stamp", phrase))
    return out


def _warning_for(cls: str, text: str) -> str:
    if cls == "PENDING_NONFINAL":
        return (
            f"⚠️ Обратите внимание: статус операции — «{text}».\n"
            "Зачисление ещё не подтверждено."
        )
    if cls == "FAILED_FINAL":
        return (
            f"❌ Статус операции — «{text}».\n"
            "Перевод не выполнен. Это не подтверждение оплаты."
        )
    if cls == "UNKNOWN_STATUS" and text:
        return f"⚠️ Статус операции не распознан: «{text}»."
    return ""


def analyze_status(text: str, *, bank_key: str = "", submethod: str = "") -> StatusResult:
    res = StatusResult()
    phrases = _extract_status_phrases(text)
    classes: set[str] = set()
    for src, phrase in phrases:
        cls = _classify_one(phrase)
        res.all_statuses.append((src, phrase, cls))
        if cls != "UNKNOWN_STATUS":
            classes.add(cls)

    if res.all_statuses:
        res.primary_text = res.all_statuses[0][1]
        res.primary_class = res.all_statuses[0][2]
    else:
        res.primary_class = "UNKNOWN_STATUS"

    if status_optional(bank_key) and not phrases:
        res.stats["status_optional"] = True
        return res

    final_classes = {c for c in classes if c in ("SUCCESS_FINAL", "FAILED_FINAL", "PENDING_NONFINAL")}
    if len(final_classes) > 1:
        res.conflict = True
        parts = [f"{src}:«{ph}»→{cls}" for src, ph, cls in res.all_statuses]
        res.conflict_detail = (
            f"G-STATUS-002: противоречивые статусы в одном PDF: {'; '.join(parts)}"
        )

    res.user_warning = _warning_for(res.primary_class, res.primary_text)
    res.stats = {
        "primary_class": res.primary_class,
        "status_count": len(phrases),
        "conflict": res.conflict,
    }
    return res
