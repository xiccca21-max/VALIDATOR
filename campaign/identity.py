"""Extract operation identity fields from PDF for campaign uniqueness."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

try:
    import fitz
except ImportError:
    fitz = None

from .config import BANK_KEY_ALIASES, MIN_OPERATION_DATE, normalize_bank_key

_OP_ID_RE = re.compile(
    r"(?:номер операции(?:\s+в\s+банке)?|номер документа|id операции|"
    r"номер операции в сбп|идентификатор операции(?:\s+в\s+сбп)?)"
    r"\s*[:\n]\s*([A-Za-z0-9\-]+)",
    re.I,
)
_SBP_RE = re.compile(
    r"(?:номер операции в сбп|id операции сбп|идентификатор операции(?:\s+в\s+сбп)?|"
    r"номер операции сбп)\s*[:\n]\s*([A-Za-z0-9]+)",
    re.I,
)
_SBP_TOKEN_RE = re.compile(r"\b([ABC][0-9A-Z]{20,})\b")
_DT_RE = re.compile(
    r"(\d{1,2})[./](\d{1,2})[./](\d{4})(?:\s+[вв]?\s*)?(\d{1,2}:\d{2}(?::\d{2})?)?"
)
_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)\s*(?:₽|руб\.?|р\.?|RUR|RUB)",
    re.I,
)
_PHONE_RE = re.compile(r"\+?7[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
_CARD_MASK_RE = re.compile(r"(?:\*{2,}|•{2,}|\d{4})[\s\*•]*(\d{4})\b")
_ACCT_MASK_RE = re.compile(r"(?:\*{2,}|•{2,}|xxxx)?\s*(\d{4})\b", re.I)

_FAILED = (
    "неуспеш", "не выполнен", "отклон", "ошибка", "отмен", "failed", "rejected",
)


def file_sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip().lower()


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text.replace("\xa0", " ")
    except Exception:
        return ""


def resolve_bank_key(text: str, producer: str, bank_name: str = "") -> tuple[str, str]:
    """Return (campaign_bank_key, display_name)."""
    try:
        from detector import profiles
        prof, _ = profiles.identify(text, producer)
        if prof:
            key = normalize_bank_key(prof.get("key") or "")
            if key:
                return key, prof.get("name") or bank_name or key
    except Exception:
        pass
    # Fallback by bank_name heuristics
    n = (bank_name or "").lower().replace("ё", "е")
    for needle, key in (
        ("т-банк", "tbank"), ("тинькофф", "tbank"),
        ("альфа", "alfa"), ("сбер", "sber"), ("втб", "vtb"),
        ("газпром", "gazprombank"), ("промсвязь", "psb"),
        ("райф", "raiffeisen"), ("озон", "ozon"), ("отп", "otp"),
        ("уралсиб", "uralsib"), ("яндекс", "yandex"),
        ("совком", "sovcombank"), ("рокет", "rocketbank"),
        ("санкт-петербург", "bchpb"), ("бспб", "bchpb"),
    ):
        if needle in n:
            return key, bank_name
    return "", bank_name or ""


def detect_method(text: str) -> str:
    t = _norm(text)
    if "сбп" in t or "быстр" in t:
        return "sbp"
    if "карт" in t:
        return "card"
    if "телефон" in t:
        return "phone"
    return "other"


def parse_operation_date(text: str) -> date | None:
    # Prefer labeled operation datetime
    labeled = re.search(
        r"(?:дата и время(?:\s+операции|\s+перевода)?|дата операции|"
        r"дата перевода)\s*[:\n]\s*"
        r"(\d{1,2})[./](\d{1,2})[./](\d{4})",
        text,
        re.I,
    )
    if labeled:
        d, m, y = int(labeled.group(1)), int(labeled.group(2)), int(labeled.group(3))
        try:
            return date(y, m, d)
        except ValueError:
            pass
    for m in _DT_RE.finditer(text[:2500]):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def operation_completed(text: str, status: str | None = None) -> bool:
    blob = _norm((status or "") + "\n" + (text or ""))
    if any(w in blob for w in _FAILED):
        return False
    # Presence of success words OR absence of failure is enough for most receipts
    ok = ("успеш", "выполн", "исполн", "заверш", "проведен", "проведён", "обработан")
    if any(w in blob for w in ok):
        return True
    # Many originals omit explicit status (Sber SBP) — treat as completed if no fail
    return True


def extract_identity(pdf_bytes: bytes, *, bank_name: str = "") -> dict[str, Any]:
    text = _pdf_text(pdf_bytes)
    producer = ""
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            producer = (doc.metadata or {}).get("producer") or ""
            doc.close()
        except Exception:
            pass

    bank_key, display = resolve_bank_key(text, producer, bank_name)
    method = detect_method(text)

    parsed: dict = {}
    try:
        from detector.parser import parse_generic, parse
        if bank_key == "tbank":
            parsed = parse(pdf_bytes)
        else:
            parsed = parse_generic(pdf_bytes, text)
    except Exception:
        parsed = {}

    sbp_id = ""
    m = _SBP_RE.search(text)
    if m:
        sbp_id = m.group(1).strip()
    if not sbp_id:
        m2 = _SBP_TOKEN_RE.search(text)
        if m2:
            sbp_id = m2.group(1)

    operation_id = ""
    m = _OP_ID_RE.search(text)
    if m:
        operation_id = m.group(1).strip()
    if sbp_id and operation_id == sbp_id:
        pass
    txn = operation_id or ""

    # Datetime string
    op_dt = ""
    labeled = re.search(
        r"(?:дата и время(?:\s+операции|\s+перевода)?|дата операции)\s*[:\n]\s*"
        r"([^\n]{8,40})",
        text,
        re.I,
    )
    if labeled:
        op_dt = labeled.group(1).strip()
    elif (m := _DT_RE.search(text[:2500])):
        op_dt = m.group(0).strip()

    amount = (parsed.get("amount") or "")
    if not amount:
        am = _AMOUNT_RE.search(text)
        amount = am.group(0) if am else ""

    sender_mask = (parsed.get("sender_card") or "")
    if not sender_mask:
        sm = _CARD_MASK_RE.search(text)
        sender_mask = sm.group(0) if sm else ""

    recipient = ""
    phone = parsed.get("contact_value") if parsed.get("contact_label", "").startswith("Телефон") else None
    if not phone:
        pm = _PHONE_RE.search(text)
        phone = pm.group(0) if pm else ""
    card = parsed.get("receiver_card") or parsed.get("contact_value")
    recipient = _norm(phone or card or parsed.get("receiver") or "")

    identity_src = "|".join([
        bank_key,
        method,
        _norm(operation_id),
        _norm(sbp_id),
        _norm(op_dt),
        _norm(amount),
        recipient,
    ])
    op_hash = hashlib.sha256(identity_src.encode("utf-8")).hexdigest() if any(
        (bank_key, operation_id, sbp_id, op_dt, amount, recipient)
    ) else ""

    # If identity is too weak (only bank), blank the hash so UNIQUE allows multiples
    strong = bool(sbp_id or operation_id or (op_dt and amount and recipient))
    if not strong:
        op_hash = ""

    op_date = parse_operation_date(text)
    status = parsed.get("status")

    return {
        "text": text,
        "producer": producer,
        "bank_key": bank_key,
        "bank_name": display,
        "method": method,
        "file_sha256": file_sha256(pdf_bytes),
        "operation_identity_hash": op_hash,
        "operation_id": operation_id or None,
        "sbp_id": sbp_id or None,
        "transaction_number": txn or None,
        "operation_datetime": op_dt or None,
        "operation_date": op_date,
        "amount_raw": amount or None,
        "sender_mask": sender_mask or None,
        "recipient_identifier": recipient or None,
        "status_text": status,
        "operation_completed": operation_completed(text, status),
        "date_ok": (op_date is None) or (op_date >= MIN_OPERATION_DATE),
        "parsed": parsed,
    }


def engine_meta(result: dict) -> tuple[str, str, str]:
    details = result.get("details") or {}
    engine = str(details.get("engine") or "")
    flags = result.get("flags") or []
    decisive = []
    for f in flags:
        s = str(f)
        if s.startswith("[") and "]" in s:
            decisive.append(s.split("]", 1)[0].strip("[]"))
    hard = int(details.get("hard_count") or 0)
    known = int(details.get("known_fake_count") or 0)
    if hard or known:
        decisive.append(f"hard={hard},known={known}")
    import json
    payload = {
        "verdict": result.get("verdict"),
        "score": result.get("score"),
        "flags": flags[:20],
        "engine": engine,
        "hard_count": hard,
        "known_fake_count": known,
        "analysis_complete": details.get("analysis_complete"),
    }
    return engine, ",".join(decisive[:30]), json.dumps(payload, ensure_ascii=False)[:8000]
