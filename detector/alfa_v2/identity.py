"""Alfa v2 cross-document operation identity.

The critical signature intentionally contains semantic transaction fields only.
PDF/container and font artefacts are used neither as evidence nor as signature
input.  A file identity is retained separately solely to establish that two
observations came from distinct files.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping


HARD_CODE = "ALFA_OPERATION_IDENTITY_CONFLICT"
RULE_ID = "ALFA-XDOC-IDENTITY-V2"

_DEFAULT_DB_PATH = Path(__file__).with_name("alfa_v2_identity.db")
_TABLE = "alfa_identity_observations_v2"
_DEFAULT_MAX_ROWS = 10_000
_DEFAULT_RETENTION_DAYS = 365

_SPACE_RE = re.compile(r"\s+")
_OPERATION_ID_RE = re.compile(r"\b[СCZ]\d{15}\b", re.IGNORECASE)
_SBP_ID_RE = re.compile(r"\b[ABАВ][0-9A-ZА-Я]{31}\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"(\d{2})[./-](\d{2})[./-](\d{4})"
    r"(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?"
)
_AMOUNT_RE = re.compile(r"([-+]?\d[\d\s\u00a0\u202f]*(?:[.,]\d{1,2})?)")
_CURRENCY_RE = re.compile(
    r"(?:\b(?:RUR|RUB|руб(?:\.|ля|лей)?)\b|₽)",
    re.IGNORECASE,
)

_LABELS: dict[str, tuple[str, ...]] = {
    "operation_id": (
        "номер операции",
        "идентификатор операции",
        "id операции",
        "код операции",
    ),
    "sbp_id": (
        "идентификатор операции в сбп",
        "идентификатор операции сбп",
        "id операции сбп",
        "номер операции в сбп",
        "сбп id",
    ),
    "amount": (
        "сумма перевода",
        "сумма операции",
        "сумма",
    ),
    "fee": (
        "сумма комиссии",
        "комиссия",
    ),
    "operation_date": (
        "дата и время перевода",
        "дата и время операции",
        "дата операции",
        "дата перевода",
    ),
    "sender": (
        "фио отправителя",
        "имя отправителя",
        "отправитель",
        "плательщик",
    ),
    "receiver": (
        "фио получателя",
        "имя получателя",
        "получатель",
    ),
    "recipient_bank": (
        "банк получателя",
        "банк зачисления",
    ),
}

_DESTINATION_LABELS: tuple[str, ...] = (
    "номер телефона получателя",
    "телефон получателя",
    "номер карты получателя",
    "карта получателя",
    "счет получателя",
    "счёт получателя",
    "счет зачисления",
    "счёт зачисления",
    "реквизиты получателя",
    "реквизиты перевода",
)

_PARSED_ALIASES: dict[str, tuple[str, ...]] = {
    "operation_id": ("operation_id", "op_id"),
    "sbp_id": ("sbp_id", "sbp_opid"),
    "submethod": ("submethod",),
    "amount": ("amount",),
    "fee": ("fee", "commission"),
    "operation_date": ("operation_date", "operation_datetime"),
    "sender": ("sender",),
    "receiver": ("receiver", "recipient"),
    "recipient_bank": ("recipient_bank",),
    "destination_requisites": ("destination_requisites",),
}


@dataclass(frozen=True)
class IdentityFields:
    operation_id: str = ""
    sbp_id: str = ""
    submethod: str = ""
    amount: str = ""
    fee: str = ""
    operation_date: str = ""
    sender: str = ""
    receiver: str = ""
    recipient_bank: str = ""
    destination_requisites: str = ""


@dataclass(frozen=True)
class IdentityFlag:
    code: str
    detail: str
    tier: str = "HARD"
    rule_id: str = RULE_ID
    group: str = "cross_document"
    identifier_type: str = ""
    identifier_value: str = ""


@dataclass
class IdentityStats:
    critical_signature: str = ""
    identifiers_checked: int = 0
    prior_observations: int = 0
    conflicts: int = 0
    observations_stored: int = 0
    observations_pruned: int = 0
    skipped: str = ""
    db_path: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class IdentityResult:
    identity: IdentityFields
    flags: list[IdentityFlag] = field(default_factory=list)
    stats: IdentityStats = field(default_factory=IdentityStats)

    @property
    def conflict(self) -> bool:
        return bool(self.flags)


def _normal_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return _SPACE_RE.sub(" ", text.replace("\x00", " ")).strip()


def _signature_text(value: object) -> str:
    return _normal_text(value).casefold()


def _normal_identifier(value: object) -> str:
    value = _normal_text(value).upper().replace("А", "A").replace("В", "B")
    return re.sub(r"[^0-9A-Z_-]", "", value)


def _normal_amount(value: object) -> str:
    raw = _normal_text(value)
    if not raw:
        return ""
    if "без комис" in raw.casefold():
        return "0"
    match = _AMOUNT_RE.search(raw)
    if not match:
        return raw.casefold()
    number = re.sub(r"\s", "", match.group(1)).replace(",", ".")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    # Currency token is not identity-critical: parse_amounts yields "4000"
    # while text extract yields "4000 RUB" for the same receipt.
    return number


def _normal_date(value: object) -> str:
    raw = _normal_text(value)
    match = _DATE_RE.search(raw)
    if not match:
        return raw.casefold()
    day, month, year, hour, minute, second = match.groups()
    result = f"{year}-{month}-{day}"
    if hour is not None:
        result += f"T{hour}:{minute}:{second or '00'}"
    return result


def _line_parts(text: str) -> list[str]:
    return [
        _normal_text(line).strip(" :")
        for line in (text or "").replace("\r", "\n").split("\n")
        if _normal_text(line).strip(" :")
    ]


def _split_label(line: str, aliases: tuple[str, ...]) -> tuple[bool, str]:
    folded = line.casefold()
    for alias in sorted(aliases, key=len, reverse=True):
        if folded == alias:
            return True, ""
        for separator in (":", " — ", " - "):
            prefix = alias + separator
            if folded.startswith(prefix):
                return True, line[len(prefix):].strip()
    return False, ""


def _all_labels() -> tuple[str, ...]:
    return tuple(
        alias
        for aliases in _LABELS.values()
        for alias in aliases
    ) + _DESTINATION_LABELS


def _looks_like_label(line: str) -> bool:
    folded = line.casefold().strip(" :")
    return any(
        folded == label or folded.startswith(label + ":")
        for label in _all_labels()
    )


def _extract_label_value(lines: list[str], aliases: tuple[str, ...]) -> str:
    for index, line in enumerate(lines):
        matched, inline = _split_label(line, aliases)
        if not matched:
            continue
        if inline:
            return inline
        if index + 1 < len(lines) and not _looks_like_label(lines[index + 1]):
            return lines[index + 1]
    return ""


def _extract_destination(lines: list[str]) -> str:
    values: list[tuple[str, str]] = []
    for alias in _DESTINATION_LABELS:
        value = _extract_label_value(lines, (alias,))
        if value:
            values.append((alias.replace("ё", "е"), _signature_text(value)))
    return "|".join(f"{label}={value}" for label, value in sorted(set(values)))


def _detect_submethod(text: str) -> str:
    folded = _signature_text(text)
    if "сбп" in folded or "системе быстрых платежей" in folded:
        return "sbp"
    if any(marker in folded for marker in ("карта получателя", "номер карты получателя")):
        return "card"
    if any(marker in folded for marker in ("по номеру телефона", "телефон получателя")):
        return "phone"
    return "unknown"


def _parsed_value(parsed: Mapping[str, object], name: str) -> object:
    for alias in _PARSED_ALIASES[name]:
        value = parsed.get(alias)
        if value is not None and str(value).strip():
            return value
    return ""


def extract_identity(
    text: str,
    *,
    submethod: str = "",
    parsed: Mapping[str, object] | None = None,
) -> IdentityFields:
    """Extract identity keys and the eight critical transaction fields.

    ``parsed`` values take precedence, allowing a later geometry-aware stage to
    supply authoritative fields while retaining this stable checking API.
    """
    parsed = parsed or {}
    lines = _line_parts(text)

    extracted = {
        name: _extract_label_value(lines, aliases)
        for name, aliases in _LABELS.items()
    }
    operation_id = _parsed_value(parsed, "operation_id") or extracted["operation_id"]
    sbp_id = _parsed_value(parsed, "sbp_id") or extracted["sbp_id"]

    compact = re.sub(r"\s+", "", text or "")
    if not operation_id:
        match = _OPERATION_ID_RE.search(compact)
        operation_id = match.group(0) if match else ""
    if not sbp_id:
        match = _SBP_ID_RE.search(compact)
        sbp_id = match.group(0) if match else ""

    method = _parsed_value(parsed, "submethod") or submethod or _detect_submethod(text)
    destination = (
        _parsed_value(parsed, "destination_requisites")
        or _extract_destination(lines)
    )

    return IdentityFields(
        operation_id=_normal_identifier(operation_id),
        sbp_id=_normal_identifier(sbp_id),
        submethod=_signature_text(method),
        amount=_normal_amount(_parsed_value(parsed, "amount") or extracted["amount"]),
        fee=_normal_amount(_parsed_value(parsed, "fee") or extracted["fee"]),
        operation_date=_normal_date(
            _parsed_value(parsed, "operation_date") or extracted["operation_date"]
        ),
        sender=_signature_text(_parsed_value(parsed, "sender") or extracted["sender"]),
        receiver=_signature_text(
            _parsed_value(parsed, "receiver") or extracted["receiver"]
        ),
        recipient_bank=_signature_text(
            _parsed_value(parsed, "recipient_bank") or extracted["recipient_bank"]
        ),
        destination_requisites=_signature_text(destination),
    )


def critical_signature(identity: IdentityFields) -> str:
    """Hash exactly the Alfa v2 critical fields, and no PDF/font metadata."""
    payload = {
        "submethod": _signature_text(identity.submethod),
        "amount": _normal_amount(identity.amount),
        "fee": _normal_amount(identity.fee),
        "operation_date": _normal_date(identity.operation_date),
        "sender": _signature_text(identity.sender),
        "receiver": _signature_text(identity.receiver),
        "recipient_bank": _signature_text(identity.recipient_bank),
        "destination_requisites": _signature_text(identity.destination_requisites),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _database_path(data_path: str | Path | None) -> Path:
    if data_path is None:
        return _DEFAULT_DB_PATH
    path = Path(data_path)
    if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
        return path
    return path / _DEFAULT_DB_PATH.name


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the append-only schema and safely add future-compatible columns."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS alfa_identity_schema (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            critical_signature TEXT NOT NULL,
            file_key TEXT NOT NULL,
            critical_fields_json TEXT NOT NULL DEFAULT '{{}}',
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        )
    """)

    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({_TABLE})")
    }
    additions = {
        "identifier_type": "TEXT NOT NULL DEFAULT ''",
        "identifier_value": "TEXT NOT NULL DEFAULT ''",
        "critical_signature": "TEXT NOT NULL DEFAULT ''",
        "file_key": "TEXT NOT NULL DEFAULT ''",
        "critical_fields_json": "TEXT NOT NULL DEFAULT '{}'",
        "first_seen": "REAL NOT NULL DEFAULT 0",
        "last_seen": "REAL NOT NULL DEFAULT 0",
        "seen_count": "INTEGER NOT NULL DEFAULT 1",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE {_TABLE} ADD COLUMN {name} {declaration}"
            )

    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_alfa_identity_lookup "
        f"ON {_TABLE}(identifier_type, identifier_value)"
    )
    # A previous interrupted migration may have left duplicate observations.
    # Collapsing only exact duplicates preserves every distinct file/signature.
    connection.execute(
        f"DELETE FROM {_TABLE} WHERE rowid NOT IN ("
        f"SELECT MAX(rowid) FROM {_TABLE} GROUP BY "
        "identifier_type, identifier_value, critical_signature, file_key"
        f")"
    )
    connection.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_alfa_identity_observation "
        f"ON {_TABLE}(identifier_type, identifier_value, critical_signature, file_key)"
    )
    connection.execute(
        "INSERT INTO alfa_identity_schema(component, version) VALUES(?, ?) "
        "ON CONFLICT(component) DO UPDATE SET version=excluded.version",
        ("identity", 1),
    )


def _critical_payload(identity: IdentityFields) -> str:
    payload = {
        key: value
        for key, value in asdict(identity).items()
        if key not in {"operation_id", "sbp_id"}
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prune(
    connection: sqlite3.Connection,
    *,
    now: float,
    max_rows: int,
    retention_days: int,
) -> int:
    before = connection.total_changes
    cutoff = now - retention_days * 86_400
    connection.execute(f"DELETE FROM {_TABLE} WHERE last_seen < ?", (cutoff,))
    count = connection.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
    excess = max(0, count - max_rows)
    if excess:
        connection.execute(
            f"DELETE FROM {_TABLE} WHERE rowid IN ("
            f"SELECT rowid FROM {_TABLE} ORDER BY last_seen ASC, rowid ASC LIMIT ?"
            f")",
            (excess,),
        )
    return connection.total_changes - before


def check_identity(
    identity: IdentityFields,
    *,
    file_id: str = "",
    pdf_bytes: bytes | None = None,
    data_path: str | Path | None = None,
    max_rows: int = _DEFAULT_MAX_ROWS,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    store: bool = True,
) -> IdentityResult:
    """Check and store an identity observation.

    First-seen signature for an identifier is canonical. A later file with
    different critical fields is HARD; it is not stored, so re-checking the
    original does not turn FAKE. Regenerated PDFs with the same fields stay
    clean. Pass store=False for files already decided FAKE (known SHA / HARD)
    so they cannot poison the first-seen slot.
    """
    stats = IdentityStats()
    result = IdentityResult(identity=identity, stats=stats)
    signature = critical_signature(identity)
    stats.critical_signature = signature

    identifiers = [
        ("operation_id", identity.operation_id),
        ("sbp_id", identity.sbp_id),
    ]
    identifiers = [(kind, value) for kind, value in identifiers if value]
    stats.identifiers_checked = len(identifiers)
    if not identifiers:
        stats.skipped = "identifier_missing"
        return result

    file_key = _normal_text(file_id)
    if not file_key and pdf_bytes is not None:
        file_key = hashlib.sha256(pdf_bytes).hexdigest()
    if not file_key:
        stats.skipped = "file_identity_missing"
        return result

    max_rows = max(1, int(max_rows))
    retention_days = max(1, int(retention_days))
    db_path = _database_path(data_path)
    stats.db_path = str(db_path)
    now = time.time()
    payload = _critical_payload(identity)

    try:
        connection = _connect(db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_schema(connection)
            for identifier_type, identifier_value in identifiers:
                rows = connection.execute(
                    f"SELECT critical_signature, file_key, first_seen FROM {_TABLE} "
                    "WHERE identifier_type=? AND identifier_value=? "
                    "ORDER BY first_seen ASC, rowid ASC",
                    (identifier_type, identifier_value),
                ).fetchall()
                stats.prior_observations += len(rows)
                canonical = rows[0] if rows else None
                disagrees_canonical = bool(
                    canonical
                    and canonical[0] != signature
                    and canonical[1] != file_key
                )
                if disagrees_canonical:
                    result.flags.append(IdentityFlag(
                        code=HARD_CODE,
                        detail=(
                            f"{identifier_type} «{identifier_value}» встречался "
                            "в другом файле с иными критическими реквизитами"
                        ),
                        identifier_type=identifier_type,
                        identifier_value=identifier_value,
                    ))

                # Conflicting newcomers are not stored — otherwise the original
                # turns FAKE on the next check against the clone we just wrote.
                if disagrees_canonical or not store:
                    continue

                cursor = connection.execute(
                    f"INSERT INTO {_TABLE}("
                    "identifier_type, identifier_value, critical_signature, file_key, "
                    "critical_fields_json, first_seen, last_seen, seen_count"
                    ") VALUES(?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(identifier_type, identifier_value, "
                    "critical_signature, file_key) DO UPDATE SET "
                    "last_seen=excluded.last_seen, seen_count=seen_count+1",
                    (
                        identifier_type,
                        identifier_value,
                        signature,
                        file_key,
                        payload,
                        now,
                        now,
                    ),
                )
                if cursor.rowcount:
                    stats.observations_stored += 1

            stats.conflicts = len(result.flags)
            stats.observations_pruned = _prune(
                connection,
                now=now,
                max_rows=max_rows,
                retention_days=retention_days,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        stats.skipped = f"store_error:{type(exc).__name__}"

    return result


def extract_and_check_identity(
    text: str,
    *,
    file_id: str = "",
    pdf_bytes: bytes | None = None,
    submethod: str = "",
    parsed: Mapping[str, object] | None = None,
    data_path: str | Path | None = None,
    max_rows: int = _DEFAULT_MAX_ROWS,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    store: bool = True,
) -> IdentityResult:
    """Convenience API for future Alfa v2 pipeline stages."""
    identity = extract_identity(text, submethod=submethod, parsed=parsed)
    return check_identity(
        identity,
        file_id=file_id,
        pdf_bytes=pdf_bytes,
        data_path=data_path,
        max_rows=max_rows,
        retention_days=retention_days,
        store=store,
    )
