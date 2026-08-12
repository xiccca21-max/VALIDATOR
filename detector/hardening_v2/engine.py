"""Hardening v2.0 orchestrator — active mode (no shadow)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .bank_contracts import contract_for, status_optional
from .document_router import route_document
from .global_rules import run_global_rules
from .status_engine import analyze_status

UNKNOWN_VERDICT = "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"


@dataclass
class HardeningResult:
    blocked: bool = False
    unknown_document: bool = False
    hard_fake: bool = False
    flags: list[str] = field(default_factory=list)
    user_message: str = ""
    status_warning: str = ""
    document_class: str = ""
    submethod: str = ""
    stats: dict = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def _unknown_result(route: dict) -> HardeningResult:
    reason = route.get("reason") or "Неподдерживаемый тип документа"
    cls = route.get("document_class", "UNKNOWN_DOCUMENT")
    if cls == "UNSUPPORTED_STATEMENT":
        msg = (
            "⚪ НЕИЗВЕСТНЫЙ ДОКУМЕНТ\n"
            "Определена банковская выписка. Этот тип документа пока не проверяется.\n"
            "Вердикт ОРИГИНАЛ/ФЕЙК не присваивался."
        )
    else:
        msg = f"⚪ НЕИЗВЕСТНЫЙ ДОКУМЕНТ\n{reason}\nВердикт ОРИГИНАЛ/ФЕЙК не присваивался."
    return HardeningResult(
        blocked=True,
        unknown_document=True,
        user_message=msg,
        document_class=cls,
        stats={"router": route},
    )


def run_hardening_v2(
    pdf_bytes: bytes,
    *,
    text: str,
    producer: str,
    bank_key: str,
) -> HardeningResult:
    """
    Pre-authenticity hardening for non-T-Bank banks.
    Active mode only — hard rules apply immediately.
    """
    out = HardeningResult()
    route = route_document(text, bank_key, producer)
    out.document_class = route.get("document_class", "")
    out.submethod = route.get("submethod", "")
    out.stats["router"] = route
    out.stats["bank_contract"] = contract_for(bank_key) or {}

    if not route.get("supported"):
        if route.get("document_class") == "RECEIPT_NEW_PROFILE":
            return _unknown_result({
                **route,
                "reason": route.get("reason") or "Новый профиль чека — пока не поддерживается",
            })
        return _unknown_result(route)

    global_res = run_global_rules(
        pdf_bytes, text=text, bank_key=bank_key, submethod=out.submethod,
    )
    out.stats["global_rules"] = global_res.stats
    out.diagnostics.extend(global_res.diagnostics)
    out.stats["rules_checked"] = global_res.rules_checked

    for rule_id, code, detail in global_res.hard_flags:
        out.hard_fake = True
        out.flags.append(f"[{code}] {detail} (rule={rule_id})")

    st = analyze_status(text, bank_key=bank_key, submethod=out.submethod)
    out.status_warning = st.user_warning
    out.stats["status_engine"] = st.stats
    if st.conflict and not out.hard_fake:
        out.hard_fake = True
        out.flags.append(f"[STATUS_INTERNAL_CONFLICT] {st.conflict_detail}")

    return out


def merge_hardening_into_result(result: dict, hardening: HardeningResult) -> dict:
    details = dict(result.get("details") or {})
    details["hardening_v2"] = {
        "document_class": hardening.document_class,
        "submethod": hardening.submethod,
        "stats": hardening.stats,
        "diagnostics": hardening.diagnostics[:12],
        "mode": "active",
    }
    if hardening.status_warning:
        details["status_warning"] = hardening.status_warning
        details["operation_status_class"] = hardening.stats.get("status_engine", {}).get(
            "primary_class", ""
        )
    result["details"] = details
    if hardening.status_warning and result.get("verdict") in ("ЧИСТО", "ОРИГИНАЛ"):
        result["status_notice"] = hardening.status_warning
    return result


def unknown_document_result(bank_name: str, hardening: HardeningResult) -> dict:
    return {
        "verdict": UNKNOWN_VERDICT,
        "emoji": "⚪",
        "score": 0,
        "flags": [],
        "details": {
            "engine": "hardening_v2",
            "document_class": hardening.document_class,
            "hardening_v2": hardening.stats,
            "bank_detected": bank_name,
        },
        "summary": hardening.user_message,
        "user_message": hardening.user_message,
    }


def hard_fake_result(hardening: HardeningResult, bank_name: str = "") -> dict:
    return {
        "verdict": "ФЕЙК",
        "emoji": "🔴",
        "score": 95,
        "flags": hardening.flags,
        "details": {
            "engine": "hardening_v2",
            "hardening_v2": hardening.stats,
            "bank_detected": bank_name,
        },
        "summary": "Обнаружена подделка (hardening v2.0).",
        "user_message": "Обнаружена подделка.",
    }
