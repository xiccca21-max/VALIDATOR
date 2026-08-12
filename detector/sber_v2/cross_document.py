"""SQLite cross-document identity + reassembled asset checks for Sber v2."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..sber_profiles import (
    extract_internal_document,
    extract_legacy_document,
    extract_sbp_opid,
    parse_operation_datetime,
)
from ..structure import content_skeleton_hash
from .types import SberFlag

_DB_ENV = "SBER_V2_IDENTITY_DB"
_DEFAULT_DB = Path(tempfile.gettempdir()) / "sber_v2_identity.db"
_AMOUNT_RE = re.compile(r"([\d\s\u00a0\u202f]+(?:[.,]\d{2})?)\s*₽")
_ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]")
_CARD_RE = re.compile(r"(\d{4}\s?\*{2,6}\s?\d{4}|\*\*\d{4})")


@dataclass
class CrossDocumentResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    identity_conflict: bool = False
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "cross_document") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def _db_path() -> Path:
    return Path(os.environ.get(_DB_ENV) or _DEFAULT_DB)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sightings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT NOT NULL,
            trailer_id TEXT,
            sbp_id TEXT,
            doc_number TEXT,
            op_date TEXT,
            amount TEXT,
            receiver TEXT,
            account_mask TEXT,
            content_ast TEXT,
            profile_id TEXT,
            seen_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sbp ON sightings(sbp_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trailer ON sightings(trailer_id)"
    )
    conn.commit()
    return conn


def _trailer_id(pdf_bytes: bytes) -> str:
    m = _ID_RE.search(pdf_bytes)
    if not m:
        return ""
    return f"{m.group(1).decode()}:{m.group(2).decode()}".lower()


def _first_amount(text: str) -> str:
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(1)).replace(",", ".")


def _receiver(text: str) -> str:
    raw = (text or "").replace("\xa0", " ")
    for label in ("получатель", "фио получателя"):
        idx = raw.lower().find(label)
        if idx >= 0:
            chunk = raw[idx:idx + 120]
            lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
            if len(lines) >= 2:
                return lines[1][:80]
    return ""


def _account_mask(text: str) -> str:
    m = _CARD_RE.search(text or "")
    return m.group(1).replace(" ", "") if m else ""


def check_cross_document_identity(
    pdf_bytes: bytes,
    text: str,
    *,
    file_hash: str = "",
    profile_id: str = "",
    record: bool = True,
) -> CrossDocumentResult:
    out = CrossDocumentResult()
    try:
        if not file_hash:
            file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        trailer = _trailer_id(pdf_bytes)
        sbp = extract_sbp_opid(text) or ""
        doc = (
            extract_legacy_document(text)
            or extract_internal_document(text)
            or ""
        )
        op = parse_operation_datetime(text)
        op_date = op.isoformat(sep=" ") if op else ""
        amount = _first_amount(text)
        receiver = _receiver(text)
        mask = _account_mask(text)
        ast = content_skeleton_hash(pdf_bytes) or ""

        out.stats.update({
            "trailer_id": trailer,
            "sbp_id": sbp,
            "doc_number": doc,
            "op_date": op_date,
            "amount": amount,
            "db": str(_db_path()),
        })

        conn = _connect()
        try:
            # Decisive identity: same SBP op-id or bank document number with
            # conflicting fields. Trailer /ID reuse alone is NOT decisive —
            # generators clone donor /ID onto rewritten receipts, so the
            # genuine donor would false-positive after a fake was sighted.
            hard_keys: list[tuple[str, str]] = []
            if sbp:
                hard_keys.append(("sbp_id", sbp))
            if doc:
                hard_keys.append(("doc_number", doc))

            for col, val in hard_keys:
                rows = conn.execute(
                    f"SELECT file_hash, amount, receiver, op_date, content_ast, account_mask "
                    f"FROM sightings WHERE {col}=? AND file_hash!=?",
                    (val, file_hash),
                ).fetchall()
                for prev_hash, p_amt, p_recv, p_date, p_ast, p_mask in rows:
                    conflicts = _field_conflicts(
                        amount, receiver, op_date, ast, mask,
                        p_amt, p_recv, p_date, p_ast, p_mask,
                    )
                    if conflicts:
                        out.identity_conflict = True
                        out.flags.append(_f(
                            "SBER_CROSS_DOCUMENT_IDENTITY_CONFLICT",
                            f"{col}={val[:24]}… конфликт с {prev_hash[:12]} "
                            f"({', '.join(conflicts)})",
                        ))
                        out.flags.append(_f(
                            "OPERATION_ID_REUSED",
                            f"повтор {col} с другими реквизитами",
                        ))
                    elif prev_hash and prev_hash != file_hash:
                        out.flags.append(_f(
                            "SBER_CROSS_DOCUMENT_WEAK_MATCH",
                            f"повторное наблюдение {col} (те же реквизиты)",
                            tier="B",
                            group="B6_cross_document_weak",
                        ))

            # Trailer /ID: observational only (shell-clone provenance hint).
            # Emit at most one Tier-B flag regardless of how many prior sightings
            # share the cloned donor /ID.
            if trailer:
                rows = conn.execute(
                    "SELECT DISTINCT file_hash, amount, receiver, op_date, "
                    "content_ast, account_mask "
                    "FROM sightings WHERE trailer_id=? AND file_hash!=?",
                    (trailer, file_hash),
                ).fetchall()
                trailer_flagged = False
                for prev_hash, p_amt, p_recv, p_date, p_ast, p_mask in rows:
                    conflicts = _field_conflicts(
                        amount, receiver, op_date, ast, mask,
                        p_amt, p_recv, p_date, p_ast, p_mask,
                    )
                    if trailer_flagged:
                        break
                    if conflicts:
                        out.flags.append(_f(
                            "SBER_CROSS_DOCUMENT_WEAK_MATCH",
                            f"trailer_id reused with different fields vs "
                            f"{prev_hash[:12]} ({', '.join(conflicts)})",
                            tier="B",
                            group="B6_cross_document_weak",
                        ))
                        trailer_flagged = True
                    elif prev_hash and prev_hash != file_hash:
                        out.flags.append(_f(
                            "SBER_CROSS_DOCUMENT_WEAK_MATCH",
                            "повторное наблюдение trailer_id (те же реквизиты)",
                            tier="B",
                            group="B6_cross_document_weak",
                        ))
                        trailer_flagged = True

            if record:
                conn.execute(
                    """
                    INSERT INTO sightings (
                        file_hash, trailer_id, sbp_id, doc_number, op_date,
                        amount, receiver, account_mask, content_ast, profile_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        file_hash, trailer, sbp, doc, op_date,
                        amount, receiver, mask, ast, profile_id,
                    ),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out


def _field_conflicts(
    amount: str, receiver: str, op_date: str, ast: str, mask: str,
    p_amt: str, p_recv: str, p_date: str, p_ast: str, p_mask: str,
) -> list[str]:
    conflicts: list[str] = []
    if amount and p_amt and amount != p_amt:
        conflicts.append(f"amount {p_amt}→{amount}")
    if receiver and p_recv and receiver != p_recv:
        conflicts.append("receiver")
    if op_date and p_date and op_date[:10] != p_date[:10]:
        conflicts.append(f"date {p_date}→{op_date}")
    if ast and p_ast and ast != p_ast and (amount != p_amt or receiver != p_recv):
        conflicts.append("content_ast+identity")
    if mask and p_mask and mask != p_mask:
        conflicts.append("account_mask")
    return conflicts


def check_reassembled_bank_assets(
    pdf_bytes: bytes,
    *,
    profile_id: str = "",
    extra_forensic_groups: set[str] | None = None,
    generator_confirmed_malicious: bool = False,
) -> CrossDocumentResult:
    """KNOWN only with confirmed generator provenance OR extra independent forensic group."""
    out = CrossDocumentResult()
    try:
        from .atlas import atlas_profile
        from .known_signatures import KNOWN_FAKE_FILE_SHA256, KNOWN_GENERATOR_SKELETONS

        file_sha = hashlib.sha256(pdf_bytes).hexdigest()
        sk = content_skeleton_hash(pdf_bytes) or ""
        out.stats["skeleton"] = sk

        if file_sha in KNOWN_FAKE_FILE_SHA256 or sk in KNOWN_GENERATOR_SKELETONS:
            out.flags.append(_f(
                "SBER_KNOWN_FAKE_SIGNATURE",
                "совпадение с известной вредоносной сигнатурой",
                tier="KNOWN",
                group="known_malicious_signature",
            ))
            return out

        # Static asset mix across incompatible profiles → diagnostic unless reinforced
        prof = atlas_profile(profile_id)
        foreign_images = 0
        # Without confirmed malicious generator, stay diagnostic
        if generator_confirmed_malicious or (extra_forensic_groups and len(extra_forensic_groups) >= 1):
            # Placeholder: only fire when caller confirms provenance
            if generator_confirmed_malicious:
                out.flags.append(_f(
                    "SBER_REASSEMBLED_BANK_ASSETS",
                    "подтверждённая пересборка банковских ассетов",
                    tier="KNOWN",
                    group="known_malicious_signature",
                ))
        else:
            out.stats["reassembled"] = "deferred_diagnostic"
            if prof:
                out.flags.append(_f(
                    "SBER_STATIC_ASSET_PROFILE_SHIFT",
                    "проверка reassembled assets отложена без provenance",
                    tier="DIAGNOSTIC",
                ))
        out.stats["foreign_images"] = foreign_images
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out


def wipe_identity_db() -> None:
    path = _db_path()
    if path.is_file():
        path.unlink()
