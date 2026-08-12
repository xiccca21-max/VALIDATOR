"""
Safe anti-edit / post-generation tamper signals.

Hard flags only when evidence is strong and verified safe on the originals corpus:
  - empty text layer + no decoded content stream (no false positives on 265 originals)
  - PDF ModDate differs from CreationDate (0 originals with drift)
  - same operation id seen before with different transaction data

Layout drift, corpus outliers and font-table drift stay soft elsewhere.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .reputation import extract_opid, file_hash
from .sbp_cipher import extract_sbp_opid

_DB_PATH = Path(__file__).with_name("anti_edit.db")

_CREATION_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
    r"(?:Z|([+-])(\d{2})'?(?:(\d{2}))?'?)?"
)
_AMOUNT_RE = re.compile(
    r"(?:сумма|итого|перевод)[^\d₽руб]{0,24}"
    r"([\d\s\u00a0\u202f]{3,}(?:[.,]\d{2})?)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?",
)
_RECEIVER_RE = re.compile(
    r"(?:получатель|телефон получателя|счёт получателя|карта получателя)"
    r"[^\n]{0,40}\n([^\n]{4,80})",
    re.IGNORECASE,
)
_PO_UUID_RE = re.compile(r"po-[0-9a-fA-F\-]{16,}", re.IGNORECASE)
_ID_LABELS = (
    "идентификатор операции",
    "номер операции",
    "id операции",
    "ид операции",
    "код операции",
    "номер документа",
    "номер квитанции",
    "id операции сбп",
)
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_]{7,}")
_MIN_TEXT_CHARS = 30
_MODDATE_DRIFT_SEC = 60
_OPID_STORE_LIMIT = 500


@dataclass
class AntiEditFlag:
    code: str
    detail: str


@dataclass
class AntiEditResult:
    flags: list[AntiEditFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS op_identity (
            opid       TEXT PRIMARY KEY,
            bank_key   TEXT,
            sig        TEXT,
            amount     TEXT,
            receiver   TEXT,
            file_hash  TEXT,
            first_seen REAL
        )
    """)
    con.commit()
    return con


def _parse_pdf_date(value: str) -> datetime | None:
    m = _CREATION_RE.match((value or "").strip())
    if not m:
        return None
    year, mo, day, hh, mm, ss = map(int, m.group(1, 2, 3, 4, 5, 6))
    sign = m.group(7)
    if sign == "+" and int(m.group(8) or 0) == 3:
        return datetime(year, mo, day, hh, mm, ss)
    dt = datetime(year, mo, day, hh, mm, ss)
    if not sign or "Z" in (value or ""):
        dt += timedelta(hours=3)
    return dt


def extract_trusted_opid(text: str) -> str | None:
    """Operation ids safe for reuse tracking — no generic long-numeric fallback."""
    raw = text or ""
    tbank = extract_opid(raw)
    if tbank and tbank.endswith("00117") and len(tbank) >= 27:
        return tbank.upper()
    sbp = extract_sbp_opid(raw)
    if sbp:
        return sbp
    mo = _PO_UUID_RE.search(raw)
    if mo:
        return mo.group(0).lower()
    low = raw.lower()
    for label in _ID_LABELS:
        pos = low.find(label)
        if pos < 0:
            continue
        window = raw[pos + len(label): pos + len(label) + 80]
        m = _ID_TOKEN_RE.search(window)
        tok = m.group(0) if m else ""
        if tok and any(c.isdigit() for c in tok) and len(tok) >= 12:
            return tok
    return None


def _norm_amount(raw: str) -> str:
    s = re.sub(r"[\s\u00a0\u202f]", "", raw or "")
    s = s.replace(",", ".")
    if re.fullmatch(r"\d{2}\.\d{2}(?:\.\d{2})?", s):
        return ""
    m = re.search(r"\d{3,}(?:\.\d{1,2})?", s)
    if m:
        return m.group(0)
    m = re.search(r"\d+(?:\.\d{1,2})?", s)
    val = m.group(0) if m else ""
    if val and re.fullmatch(r"\d{2}\.\d{2}", val):
        return ""
    return val


def _extract_amount(text: str) -> str:
    for m in _AMOUNT_RE.finditer(text or ""):
        val = _norm_amount(m.group(1))
        if val:
            return val
    return ""


def _extract_operation_date(text: str) -> str:
    low = (text or "").lower().replace("\xa0", " ")
    labels = (
        "дата и время операции",
        "дата операции",
        "дата и время перевода",
        "дата платежа",
    )
    for label in labels:
        idx = low.find(label)
        if idx < 0:
            continue
        m = _DATE_RE.search(text[idx: idx + 120])
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    m = _DATE_RE.search(text or "")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""


def _extract_receiver(text: str) -> str:
    m = _RECEIVER_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip().lower()[:80]


def transaction_signature(
    text: str,
    parsed: dict | None = None,
) -> tuple[str, dict]:
    """Stable signature for reuse detection (amount + date + receiver)."""
    if parsed:
        amount = _norm_amount(str(parsed.get("amount", "")))
        receiver = str(parsed.get("receiver", "") or "").strip().lower()[:80]
        date = str(parsed.get("date", "") or "").strip()
        if not date:
            date = _extract_operation_date(text)
    else:
        amount = _extract_amount(text)
        receiver = _extract_receiver(text)
        date = _extract_operation_date(text)
    parts = {
        "amount": amount,
        "date": date,
        "receiver": receiver,
    }
    sig = "|".join(parts.values())
    return sig, parts


def check_text_layer(
    text: str,
    content_decoded: int,
    *,
    bank_key: str = "",
) -> list[AntiEditFlag]:
    """Hard when a routed bank receipt has no extractable text and no content stream."""
    if content_decoded > 0:
        return []
    if len((text or "").strip()) >= _MIN_TEXT_CHARS:
        return []
    return [AntiEditFlag(
        "RECEIPT_TEXT_LAYER_MISSING",
        "в PDF нет текстового слоя и content stream — "
        "оригинальные банковские чеки всегда содержат извлекаемый текст",
    )]


def check_metadata_edit(
    creation_date: str,
    mod_date: str,
) -> list[AntiEditFlag]:
    """Hard when ModDate was changed after initial export (0 drift cases in originals)."""
    if not creation_date or not mod_date:
        return []
    created = _parse_pdf_date(creation_date)
    modified = _parse_pdf_date(mod_date)
    if not created or not modified:
        return []
    delta = abs((modified - created).total_seconds())
    if delta <= _MODDATE_DRIFT_SEC:
        return []
    return [AntiEditFlag(
        "PDF_MODDATE_EDITED",
        f"дата изменения PDF ({mod_date}) отличается от даты создания "
        f"({creation_date}) — признак редактирования файла",
    )]


def check_operation_identity(
    *,
    bank_key: str,
    text: str,
    pdf_bytes: bytes,
    parsed: dict | None = None,
    file_hash_value: str = "",
) -> tuple[list[AntiEditFlag], dict]:
    """
    Hard only when the same operation id was already seen with different
    transaction data (amount/date/receiver). First sight is always clean.
    """
    fh = file_hash_value or file_hash(pdf_bytes)
    opid = extract_trusted_opid(text)
    stats: dict = {"opid": opid, "file_hash": fh}
    if not opid or len(opid) < 12:
        return [], stats

    sig, parts = transaction_signature(text, parsed)
    stats.update(parts)
    stats["sig"] = sig
    if not parts.get("amount") or not parts.get("date"):
        return [], stats

    con = _con()
    try:
        row = con.execute(
            "SELECT sig, file_hash, bank_key FROM op_identity WHERE opid=?",
            (opid,),
        ).fetchone()
        if row:
            prev_sig, prev_hash, prev_bank = row
            stats["prev_sig"] = prev_sig
            stats["prev_bank"] = prev_bank
            if prev_sig != sig and prev_hash != fh:
                return [AntiEditFlag(
                    "OPERATION_ID_REUSED",
                    f"идентификатор операции ({opid}) уже встречался "
                    f"с другими реквизитами — вероятно переработанный чужой чек",
                )], stats
        else:
            con.execute(
                "INSERT INTO op_identity(opid,bank_key,sig,amount,receiver,file_hash,first_seen)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    opid,
                    bank_key,
                    sig,
                    parts.get("amount", ""),
                    parts.get("receiver", ""),
                    fh,
                    time.time(),
                ),
            )
            con.execute("""
                DELETE FROM op_identity WHERE opid NOT IN (
                    SELECT opid FROM op_identity ORDER BY first_seen DESC LIMIT ?
                )
            """, (_OPID_STORE_LIMIT,))
        con.commit()
    finally:
        con.close()
    return [], stats


def run_checks(
    pdf_bytes: bytes,
    *,
    bank_key: str,
    text: str,
    content_decoded: int,
    creation_date: str = "",
    mod_date: str = "",
    parsed: dict | None = None,
    file_hash_value: str = "",
) -> AntiEditResult:
    flags: list[AntiEditFlag] = []
    stats: dict = {}

    flags.extend(check_text_layer(text, content_decoded, bank_key=bank_key))
    flags.extend(check_metadata_edit(creation_date, mod_date))

    reuse_flags, reuse_stats = check_operation_identity(
        bank_key=bank_key,
        text=text,
        pdf_bytes=pdf_bytes,
        parsed=parsed,
        file_hash_value=file_hash_value,
    )
    flags.extend(reuse_flags)
    stats["operation_identity"] = reuse_stats

    return AntiEditResult(flags=flags, stats=stats)
