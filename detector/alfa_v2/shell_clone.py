"""Oracle shell clone and trailer-/ID reuse detection for Alfa v2."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .pdfutil import objects, stream_role
from .profile_semantics import (
    classify_submethod,
    extract_operation_datetime,
    extract_operation_ids,
    parse_amounts,
)
from .types import ForensicResult

ATLAS_DIR = Path(__file__).with_name("atlas_data")
RULE_GROUP = "alfa_v2.shell_clone"
_DEFAULT_DB = Path(__file__).with_name("alfa_v2_trailer_id.db")
_ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_PHONE_RE = re.compile(r"\+7[\d\s()_-]{10,}")
_ACCOUNT_RE = re.compile(r"\b40817\d{15}\b")
_BANK_RE = re.compile(
    r"(сбербанк|тинькофф|т-банк|втб|альфа-банк|газпромбанк|отп банк)",
    re.I,
)


def extract_trailer_id(pdf: bytes) -> str:
    match = _ID_RE.search(pdf or b"")
    if not match:
        return ""
    return match.group(1).decode("ascii").lower()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash(pdf: bytes) -> str:
    digests = []
    for obj in objects(pdf).values():
        if stream_role(obj) == "content" and obj.decoded_stream is not None:
            digests.append(_sha(obj.decoded_stream))
    return _sha("\n".join(digests).encode()) if digests else ""


def _object_decoded_map(pdf: bytes) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for number, obj in objects(pdf).items():
        if obj.decoded_stream is None:
            continue
        out[number] = {
            "role": stream_role(obj),
            "decoded_sha256": _sha(obj.decoded_stream),
        }
    return out


def _static_image_hashes(pdf: bytes) -> set[str]:
    values: set[str] = set()
    for obj in objects(pdf).values():
        if stream_role(obj) == "image" and obj.decoded_stream is not None:
            values.add(_sha(obj.decoded_stream))
    return values


def _load_shell_registry() -> dict[str, Any]:
    path = ATLAS_DIR / "shell_registry.v1.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _operation_identity(text: str) -> dict[str, str]:
    method = classify_submethod(text)
    amounts = parse_amounts(text)
    dt = extract_operation_datetime(text)
    op_ids = extract_operation_ids(text)
    phone = _PHONE_RE.search(text or "")
    account = _ACCOUNT_RE.search(text or "")
    bank = _BANK_RE.search(text or "")
    receiver = ""
    for label in ("получатель", "фио получателя"):
        match = re.search(
            label + r"\s*[:\n]\s*([^\n]+)",
            text or "",
            re.I,
        )
        if match:
            receiver = match.group(1).strip()
            break
    return {
        "method": method,
        "amount": str(amounts.amount) if amounts.amount is not None else "",
        "fee": str(amounts.fee) if amounts.fee is not None else "",
        "operation_datetime": dt.strftime("%d.%m.%Y %H:%M:%S") if dt else "",
        "operation_id": op_ids[0] if op_ids else "",
        "receiver": receiver,
        "phone": re.sub(r"\D", "", phone.group(0)) if phone else "",
        "recipient_bank": bank.group(1).lower() if bank else "",
        "debit_account": account.group(0) if account else "",
        "sbp_id": "",
    }


def _identity_changed(current: dict[str, str], registered: dict[str, str]) -> bool:
    keys = (
        "method",
        "amount",
        "fee",
        "operation_datetime",
        "operation_id",
        "receiver",
        "phone",
        "recipient_bank",
        "debit_account",
        "sbp_id",
    )
    comparable = 0
    changed = 0
    for key in keys:
        left, right = (current.get(key) or "").strip(), (registered.get(key) or "").strip()
        if not left or not right:
            continue
        comparable += 1
        if left != right:
            changed += 1
    # Fall back to operation_id / amount alone when labels are glyph-corrupted.
    if comparable == 0:
        for key in ("operation_id", "amount", "operation_datetime"):
            left, right = (current.get(key) or "").strip(), (registered.get(key) or "").strip()
            if left and right and left != right:
                return True
        return bool(current.get("operation_id") and registered.get("operation_id")
                    and current["operation_id"] != registered["operation_id"])
    return changed >= 1


def _graph_overlap(current: dict[int, dict[str, str]], registered: dict[str, Any]) -> tuple[int, int]:
    reg_objects = registered.get("objects") or {}
    matched = 0
    total = 0
    for key, meta in reg_objects.items():
        total += 1
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        cur = current.get(number)
        if cur and cur.get("decoded_sha256") == meta.get("decoded_sha256"):
            matched += 1
    return matched, total


def _ensure_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trailer_observations (
            trailer_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            identity_json TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            seen_at REAL NOT NULL,
            PRIMARY KEY (trailer_id, content_sha256)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trailer_canonical (
            trailer_id TEXT PRIMARY KEY,
            content_sha256 TEXT NOT NULL,
            identity_json TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            seen_at REAL NOT NULL
        )
        """
    )
    return conn


def check_shell_clone(
    pdf: bytes,
    text: str,
    *,
    file_hash: str = "",
    producer: str = "",
    db_path: Path | None = None,
) -> ForensicResult:
    result = ForensicResult()
    trailer_id = extract_trailer_id(pdf)
    content_sha = _content_hash(pdf)
    identity = _operation_identity(text)
    current_objects = _object_decoded_map(pdf)
    current_images = _static_image_hashes(pdf)
    result.stats.update(
        trailer_id=trailer_id,
        content_sha256=content_sha,
        identity=identity,
        object_count=len(current_objects),
    )
    if not trailer_id or not content_sha:
        result.stats["skipped"] = "trailer_or_content_unavailable"
        return result

    registry = _load_shell_registry()
    entries = registry.get("by_trailer_id") or {}
    registered = entries.get(trailer_id) if isinstance(entries, dict) else None
    producer_l = (producer or "").lower()
    oracle_shell = "oracle bi publisher" in producer_l or (
        isinstance(registered, dict) and registered.get("emitter") == "oracle"
    )

    if isinstance(registered, dict):
        reg_content = str(registered.get("content_sha256") or "")
        reg_images = set(registered.get("image_decoded_sha256") or [])
        matched_objects, total_objects = _graph_overlap(current_objects, registered)
        images_match = bool(reg_images) and reg_images.issubset(current_images)
        content_changed = bool(reg_content) and reg_content != content_sha
        fields_changed = _identity_changed(identity, registered.get("identity") or {})
        result.stats.update(
            registry_hit=True,
            registry_content_sha256=reg_content,
            object_graph_overlap=f"{matched_objects}/{total_objects}",
            static_assets_match=images_match,
            content_changed=content_changed,
            critical_fields_changed=fields_changed,
        )
        if (
            oracle_shell
            and content_changed
            and images_match
            and total_objects >= 4
            and matched_objects >= max(3, total_objects - 1)
            and fields_changed
        ):
            result.add(
                "ALFA_CLONED_ORIGINAL_SHELL_CONTENT_REWRITE",
                "Oracle shell/object graph/static assets/trailer ID match a registered "
                "original while decoded page content and critical operation fields differ",
                group=RULE_GROUP,
                evidence={
                    "trailer_id": trailer_id,
                    "object_graph_overlap": f"{matched_objects}/{total_objects}",
                    "registered_file_sha256": registered.get("file_sha256"),
                },
            )
        # Oracle BI Publisher stamps the same trailer /ID on many genuine receipts.
        # Content-only mismatch is normal — do NOT HARD on trailer reuse alone.
        if content_changed and not oracle_shell:
            result.add(
                "ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT",
                "trailer /ID reused with a different decoded page-content hash than the "
                "registered Alfa original",
                group=RULE_GROUP,
                evidence={
                    "trailer_id": trailer_id,
                    "content_sha256": content_sha,
                    "registered_content_sha256": reg_content,
                },
            )

    # Runtime reuse across distinct uploads (non-corpus first sightings).
    conn = _ensure_db(db_path or _DEFAULT_DB)
    try:
        row = conn.execute(
            "SELECT content_sha256, identity_json, file_hash FROM trailer_canonical WHERE trailer_id=?",
            (trailer_id,),
        ).fetchone()
        now = time.time()
        identity_json = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        if row:
            prev_content, prev_identity_json, prev_file = row
            prev_identity = json.loads(prev_identity_json or "{}")
            if prev_content != content_sha or _identity_changed(identity, prev_identity):
                # Same as registry path: Oracle reuses /ID across real receipts.
                if not oracle_shell and not any(
                    f.code == "ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT"
                    for f in result.flags
                ):
                    result.add(
                        "ALFA_TRAILER_ID_REUSED_WITH_DIFFERENT_CONTENT",
                        "trailer /ID reused with different content stream or operation identity",
                        group=RULE_GROUP,
                        evidence={
                            "trailer_id": trailer_id,
                            "previous_file_hash": prev_file,
                            "content_sha256": content_sha,
                            "previous_content_sha256": prev_content,
                        },
                    )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO trailer_canonical "
                "(trailer_id, content_sha256, identity_json, file_hash, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (trailer_id, content_sha, identity_json, file_hash, now),
            )
        conn.execute(
            "INSERT OR IGNORE INTO trailer_observations "
            "(trailer_id, content_sha256, identity_json, file_hash, seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (trailer_id, content_sha, identity_json, file_hash, now),
        )
        conn.commit()
    finally:
        conn.close()
    return result
