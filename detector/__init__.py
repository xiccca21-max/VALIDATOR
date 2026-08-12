"""T-Bank PDF receipt detector entry points."""

from __future__ import annotations

import logging

from .hardening_v2.engine import (
    hard_fake_result,
    merge_hardening_into_result,
    run_hardening_v2,
    unknown_document_result,
)
from .hardening_v2.global_preflight import run_global_preflight
from .hardening_v2.verdict_merge import apply_v2_priority, has_decisive_evidence
from .recipient_bank import attach_recipient_bank_fields
from .tbank import analyze as analyze_tbank
from .pdf_forensics import run_pdf_forensics, forensics_to_log_dict
from . import profiles
from .vtb_known_hashes import check_vtb_known_file_hash

log = logging.getLogger(__name__)

__all__ = [
    "analyze_tbank",
    "run_pdf_forensics",
    "forensics_to_log_dict",
    "route",
]


def _analysis_not_completed(reason: str) -> dict:
    return {
        "verdict": "ФЕЙК",
        "emoji": "🔴",
        "score": 95,
        "flags": [f"[ANALYSIS_NOT_COMPLETED] {reason}"],
        "details": {"analysis_complete": False},
        "summary": "Файл невозможно полноценно проверить.",
    }


def _preflight_fake(preflight, bank_name: str) -> dict:
    from .hardening_v2.engine import HardeningResult
    h = HardeningResult(hard_fake=True, flags=preflight.flags, stats={"preflight": preflight.stats})
    return hard_fake_result(h, bank_name)


def _log_vtb_path(stage: str, **fields) -> None:
    parts = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    log.info("vtb_path %s %s", stage, parts)


def route(pdf_bytes: bytes) -> tuple[str, dict, bool]:
    """Identify bank and run the appropriate detector."""
    import hashlib
    import fitz

    file_sha = hashlib.sha256(pdf_bytes).hexdigest()

    # Global VTB known-file hard-block — before rollout / legacy / normalize.
    known_vtb_fake = check_vtb_known_file_hash(pdf_bytes)
    if known_vtb_fake is not None:
        _log_vtb_path(
            "known_file_hard_block",
            file_sha256=file_sha,
            identified_bank="Банк ВТБ",
            selected_engine="vtb_known_signatures",
            verdict="ФЕЙК",
            known_fake_count=1,
            first_decisive_flag="VTB_KNOWN_FILE_SIGNATURE",
        )
        return "Банк ВТБ", known_vtb_fake, False

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        producer = (doc.metadata.get("producer", "") or "")
        text = "".join(p.get_text() for p in doc)
        doc.close()
    except Exception:
        producer, text = "", ""

    prof, _ = profiles.identify(text, producer)
    bank_name = prof["name"] if prof else "Неизвестный банк"
    bank_key = prof["key"] if prof else ""
    is_tbank = bool(prof and prof["key"] == "tbank")

    pre = run_global_preflight(
        pdf_bytes, text=text, bank_key=bank_key, submethod="",
    )
    if pre.hard_fake:
        return bank_name, _preflight_fake(pre, bank_name), is_tbank

    if is_tbank:
        try:
            result = profiles.analyze_for("tbank", pdf_bytes)
        except Exception as exc:
            result = _analysis_not_completed(f"ошибка анализатора: {exc}")
        from .hardening_v2.status_engine import analyze_status
        st = analyze_status(text, bank_key="tbank")
        if st.user_warning:
            result["status_notice"] = st.user_warning
            details = dict(result.get("details") or {})
            details["status_warning"] = st.user_warning
            details["operation_status_class"] = st.primary_class
            result["details"] = details
        details = dict(result.get("details") or {})
        details["global_preflight"] = pre.stats
        result["details"] = attach_recipient_bank_fields(
            details, pdf_bytes, text, issuer_bank=prof["name"],
        )
        return prof["name"], result, True

    if bank_key:
        hardening = run_hardening_v2(
            pdf_bytes, text=text, producer=producer, bank_key=bank_key,
        )
        if hardening.unknown_document:
            return bank_name, unknown_document_result(bank_name, hardening), False
        if hardening.hard_fake:
            return bank_name, hard_fake_result(hardening, bank_name), False

        try:
            result = profiles.analyze_for(bank_key, pdf_bytes)
        except Exception as exc:
            result = _analysis_not_completed(f"ошибка анализатора: {exc}")

        if bank_key == "vtb":
            d0 = result.get("details") or {}
            _log_vtb_path(
                "after_engine",
                file_sha256=file_sha,
                identified_bank=bank_name,
                selected_engine=d0.get("engine"),
                rollout_mode=d0.get("rollout_mode"),
                engine_verdict_before_rollout=d0.get("engine_verdict_before_rollout")
                or result.get("verdict"),
                hard_count=d0.get("hard_count"),
                known_fake_count=d0.get("known_fake_count"),
                first_decisive_flag=(
                    (result.get("flags") or [None])[0]
                ),
            )

        result = merge_hardening_into_result(result, hardening)
        # Never let merge/priority turn decisive FAKE into ЧИСТО.
        if has_decisive_evidence(result):
            result["verdict"] = "ФЕЙК"
            result["emoji"] = "🔴"
            result["score"] = max(int(result.get("score") or 0), 95)
        else:
            result = apply_v2_priority(result, hardening_hard=False)

        # NOT_SBER_RECEIPT means the file is not a Sber receipt at all —
        # do not label it as «fake Sberbank»; surface as unknown bank.
        flags_now = result.get("flags") or []
        if any("NOT_SBER_RECEIPT" in str(f) for f in flags_now):
            bank_name = "Неизвестный банк"
            result["verdict"] = "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"
            result["emoji"] = "⚪"
            result["score"] = 0
            details_ns = dict(result.get("details") or {})
            details_ns["not_sber_receipt"] = True
            details_ns["hard_count"] = 0
            details_ns["known_fake_count"] = 0
            result["details"] = details_ns
            result["user_message"] = "Неизвестный банк"
            result["summary"] = "Неизвестный банк"

        if bank_key == "vtb":
            d1 = result.get("details") or {}
            _log_vtb_path(
                "after_v2_priority",
                file_sha256=file_sha,
                verdict_after_v2_priority=result.get("verdict"),
                hard_count=d1.get("hard_count"),
                known_fake_count=d1.get("known_fake_count"),
                score=result.get("score"),
            )

        details = dict(result.get("details") or {})
        result["details"] = attach_recipient_bank_fields(
            details, pdf_bytes, text, issuer_bank=bank_name,
        )
        return bank_name, result, False

    from .generic_bank import analyze as generic_analyze
    result = generic_analyze(pdf_bytes, "unknown")
    return "Неизвестный банк", result, False


BANK_DETECTORS = {"tbank": analyze_tbank}
