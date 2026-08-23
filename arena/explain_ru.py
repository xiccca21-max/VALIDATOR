"""Human-readable Russian labels for dashboard receipts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SUBMETHOD_LABELS = {
    "sbp": "СБП",
    "phone": "По телефону",
    "card": "Карта",
    "card_sber": "Карта → Сбер",
    "card_tbank": "Карта → Т-Банк",
    "nocomm": "Без комиссии",
    "statement": "Выписка",
}

MUTATION_LABELS = {
    "xref_object_mismatch": "таблица ссылок указывает не на тот объект",
    "xref_generation_mismatch": "не совпадает поколение объекта в xref",
    "xref_duplicate_live_mapping": "один объект записан в xref дважды",
    "xref_size_conflict": "размер xref не сходится с числом объектов",
    "stream_length_overrun": "длина потока больше, чем есть в файле",
    "stream_length_type_invalid": "у потока указан неверный тип длины",
    "duplicate_contents": "у страницы два разных содержимых",
    "page_count_conflict": "число страниц не совпадает с деревом",
    "page_parent_conflict": "страница ссылается на чужого родителя",
    "missing_contents_reference": "страница ссылается на несуществующее содержимое",
    "contents_generation_mismatch": "ссылка на содержимое с чужим поколением",
}

CODE_LABELS = {
    "ALFA_RUR_TRAILING_NBSP_ASYMMETRY": "суммы в рублях собраны неровно, как после правки текста",
    "ALFA_CONTENT_ET_WHITESPACE_ANOMALY": "в тексте страницы странные пробелы — след ручной правки",
    "ALFA_ORACLE_SFNT_HINTING_TABLES_MISSING": "шрифт пересобран, пропали служебные таблицы",
    "ALFA_FONTFILE2_SIZE_UNDERSIZE": "встроенный шрифт меньше, чем бывает у настоящих чеков",
    "ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT": "контрольная сумма шрифта не как у оригинала Альфа",
    "ALFA_OPERATION_IDENTITY_CONFLICT": "номер операции уже встречался в другом чеке с другими данными",
    "XREF_ENTRY_OBJECT_MISMATCH": "таблица ссылок PDF указывает не на тот объект",
    "XREF_GENERATION_MISMATCH": "поколение объекта в PDF не совпадает",
    "XREF_DUPLICATE_LIVE_MAPPING": "один объект записан в таблице ссылок дважды",
    "XREF_SIZE_CONTRADICTION": "размер таблицы ссылок не сходится",
    "STREAM_ENDSTREAM_CONTRADICTION": "длина потока не совпадает с реальным содержимым",
    "STREAM_LENGTH_TYPE_INVALID": "у потока указан неверный тип длины",
    "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT": "в словаре PDF одно поле записано дважды",
    "PAGETREE_COUNT_CONTRADICTION": "число страниц не сходится",
    "PAGETREE_PARENT_CONTRADICTION": "страница ссылается на чужого родителя",
    "PAGE_CONTENT_REFERENCE_INVALID": "страница ссылается на несуществующее содержимое",
    "INDIRECT_REFERENCE_GENERATION_MISMATCH": "ссылка указывает на объект с чужим поколением",
}

_FLAG_RE = re.compile(r"^\[([A-Z0-9_]+)\]\s*(.*)$")


def filename(path: str) -> str:
    return Path(path).name


def infer_submethod(
    path: str,
    details: dict[str, Any] | None = None,
    flags: list[str] | tuple[str, ...] = (),
) -> str:
    details = details or {}
    raw = str(
        details.get("receipt_subtype_label")
        or details.get("channel")
        or details.get("submethod")
        or (details.get("stats") or {}).get("receipt_channel")
        or ""
    ).strip().lower()
    blob = f"{raw} {path} {' '.join(flags)}".lower().replace("\\", "/")
    if "nocomm" in blob or "без комиссии" in blob:
        return SUBMETHOD_LABELS["nocomm"]
    if "card_tbank" in blob or "карта → т" in blob:
        return SUBMETHOD_LABELS["card_tbank"]
    if "card_sber" in blob or "карта → сбер" in blob:
        return SUBMETHOD_LABELS["card_sber"]
    if "statement" in blob or "выписк" in blob:
        return SUBMETHOD_LABELS["statement"]
    if "phone" in blob or "телефон" in blob:
        return SUBMETHOD_LABELS["phone"]
    if "sbp" in blob or "сбп" in blob:
        return SUBMETHOD_LABELS["sbp"]
    if "card" in blob or "карт" in blob:
        return SUBMETHOD_LABELS["card"]
    return SUBMETHOD_LABELS.get(raw, "Неизвестно")


def _from_flag(flag: str) -> str:
    match = _FLAG_RE.match(str(flag).strip())
    if not match:
        return str(flag).strip()
    code, detail = match.group(1), match.group(2).strip()
    if code in CODE_LABELS:
        return CODE_LABELS[code]
    cleaned = detail.split(" — ")[0].split(";")[0]
    cleaned = re.sub(r"\(примеры:.*?\)", "", cleaned)
    cleaned = cleaned.replace("\\xa0", " ").replace("\xa0", " ").strip(" -")
    if cleaned and not cleaned[:1].isascii():
        return cleaned
    return cleaned or code


def why_caught(flags: list[str] | tuple[str, ...], mutations: list[str] | None = None) -> str:
    if mutations:
        labels = [MUTATION_LABELS.get(name, name) for name in mutations]
        return "Структура PDF сломана: " + "; ".join(labels) + "."
    reasons = []
    for flag in flags[:3]:
        text = _from_flag(flag)
        if text and text not in reasons:
            reasons.append(text)
    if not reasons:
        return "Признаки подделки не названы."
    return "Пойман, потому что " + "; ".join(reasons) + "."


def why_missed() -> str:
    return "Валидатор не нашёл жёстких противоречий и сказал «чисто»."


def describe_receipt(
    *,
    path: str,
    bank: str,
    verdict: str,
    flags: list[str] | tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
    mutations: list[str] | None = None,
    caught: bool | None = None,
) -> dict[str, str]:
    is_caught = bool(caught) if caught is not None else str(verdict).upper() in {"FAKE", "ФЕЙК"}
    if is_caught:
        why = why_caught(list(flags), mutations)
        result = "Пойман"
    elif str(verdict).upper() in {"ERROR"}:
        why = "Проверка сломалась, вердикта нет."
        result = "Ошибка"
    else:
        why = why_missed()
        result = "Пропущен"
    return {
        "name": filename(path),
        "bank": bank or "Неизвестный банк",
        "submethod": infer_submethod(path, details, flags),
        "result": result,
        "why": why,
    }
