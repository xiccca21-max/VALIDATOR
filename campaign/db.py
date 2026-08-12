"""Campaign SQLite schema, ledger, uniqueness."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import (
    CAMPAIGN_ID,
    CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS,
    LEDGER_CREDIT,
    LEDGER_DEBIT,
    LEDGER_PAYOUT,
    LEDGER_REVERSE,
    PAYOUT_PENDING,
    STATUS_ACCEPTED,
    STATUS_PENDING,
    now_msk,
)

_DB_PATH = Path(os.environ.get(
    "CAMPAIGN_DB_PATH",
    Path(__file__).resolve().parent.parent / "data" / "campaign.db",
))
_LOCK = threading.RLock()


def _ts() -> str:
    return now_msk().strftime("%Y-%m-%d %H:%M:%S")


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with _LOCK:
        con = _connect()
        try:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaign_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    status TEXT NOT NULL,
                    bank_key TEXT,
                    bank_name TEXT,
                    method TEXT,
                    file_sha256 TEXT,
                    operation_identity_hash TEXT,
                    operation_id TEXT,
                    sbp_id TEXT,
                    transaction_number TEXT,
                    operation_datetime TEXT,
                    amount_raw TEXT,
                    sender_mask TEXT,
                    recipient_identifier TEXT,
                    verdict TEXT,
                    engine_version TEXT,
                    decisive_flags TEXT,
                    validator_result_json TEXT,
                    reward_kopecks INTEGER NOT NULL DEFAULT 0,
                    reject_reason_code TEXT,
                    reject_reason_text TEXT,
                    moderator_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ux_campaign_file_sha
                    ON campaign_checks(file_sha256)
                    WHERE file_sha256 IS NOT NULL AND file_sha256 != '';

                CREATE UNIQUE INDEX IF NOT EXISTS ux_campaign_op_identity
                    ON campaign_checks(operation_identity_hash)
                    WHERE operation_identity_hash IS NOT NULL
                      AND operation_identity_hash != '';

                CREATE INDEX IF NOT EXISTS ix_campaign_user
                    ON campaign_checks(user_id, status);
                CREATE INDEX IF NOT EXISTS ix_campaign_status
                    ON campaign_checks(status);
                CREATE INDEX IF NOT EXISTS ix_campaign_bank
                    ON campaign_checks(bank_key);

                CREATE TABLE IF NOT EXISTS balance_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    check_id INTEGER,
                    operation_type TEXT NOT NULL,
                    amount_kopecks INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    admin_id INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(check_id, operation_type)
                        ON CONFLICT ABORT
                );

                CREATE INDEX IF NOT EXISTS ix_ledger_user
                    ON balance_ledger(user_id);

                CREATE TABLE IF NOT EXISTS campaign_payouts (
                    user_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending_payout',
                    amount_kopecks INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    admin_id INTEGER,
                    paid_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS campaign_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    admin_username TEXT,
                    action TEXT NOT NULL,
                    target_user_id INTEGER,
                    check_id INTEGER,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Soften UNIQUE(check_id, operation_type): reverse can coexist with credit.
            # Recreate without unique on all types — use partial uniqueness in app.
            # SQLite can't easily alter; keep UNIQUE and use reverse as separate rows
            # with operation_type 'reverse' once per check_id (OK).
            # Multiple debit/adjust need check_id NULL — allowed (multiple NULLs).
        finally:
            con.close()


@contextmanager
def db_tx() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        con = _connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


def audit(
    con: sqlite3.Connection,
    *,
    admin_id: int | None,
    admin_username: str | None,
    action: str,
    target_user_id: int | None = None,
    check_id: int | None = None,
    detail: str = "",
) -> None:
    con.execute(
        """INSERT INTO campaign_audit
           (admin_id, admin_username, action, target_user_id, check_id, detail, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (admin_id, admin_username, action, target_user_id, check_id, detail, _ts()),
    )


def insert_pending_check(con: sqlite3.Connection, row: dict[str, Any]) -> int:
    cur = con.execute(
        """INSERT INTO campaign_checks (
            campaign_id, user_id, username, status, bank_key, bank_name, method,
            file_sha256, operation_identity_hash, operation_id, sbp_id,
            transaction_number, operation_datetime, amount_raw, sender_mask,
            recipient_identifier, verdict, engine_version, decisive_flags,
            validator_result_json, reward_kopecks, reject_reason_code,
            reject_reason_text, moderator_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,NULL,NULL,?,?)""",
        (
            CAMPAIGN_ID,
            row["user_id"],
            row.get("username"),
            STATUS_PENDING,
            row.get("bank_key"),
            row.get("bank_name"),
            row.get("method"),
            row.get("file_sha256") or None,
            row.get("operation_identity_hash") or None,
            row.get("operation_id"),
            row.get("sbp_id"),
            row.get("transaction_number"),
            row.get("operation_datetime"),
            row.get("amount_raw"),
            row.get("sender_mask"),
            row.get("recipient_identifier"),
            row.get("verdict"),
            row.get("engine_version"),
            row.get("decisive_flags"),
            row.get("validator_result_json"),
            _ts(),
            _ts(),
        ),
    )
    return int(cur.lastrowid)


def find_by_hashes(
    con: sqlite3.Connection,
    file_sha256: str | None,
    operation_identity_hash: str | None,
) -> sqlite3.Row | None:
    if file_sha256:
        row = con.execute(
            "SELECT * FROM campaign_checks WHERE file_sha256 = ? LIMIT 1",
            (file_sha256,),
        ).fetchone()
        if row:
            return row
    if operation_identity_hash:
        return con.execute(
            "SELECT * FROM campaign_checks WHERE operation_identity_hash = ? LIMIT 1",
            (operation_identity_hash,),
        ).fetchone()
    return None


def get_check(con: sqlite3.Connection, check_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM campaign_checks WHERE id = ?", (check_id,)
    ).fetchone()


def update_check_status(
    con: sqlite3.Connection,
    check_id: int,
    status: str,
    *,
    reason_code: str | None = None,
    reason_text: str | None = None,
    moderator_id: int | None = None,
    reward_kopecks: int | None = None,
) -> None:
    fields = ["status = ?", "updated_at = ?"]
    vals: list[Any] = [status, _ts()]
    if reason_code is not None:
        fields.append("reject_reason_code = ?")
        vals.append(reason_code)
    if reason_text is not None:
        fields.append("reject_reason_text = ?")
        vals.append(reason_text)
    if moderator_id is not None:
        fields.append("moderator_id = ?")
        vals.append(moderator_id)
    if reward_kopecks is not None:
        fields.append("reward_kopecks = ?")
        vals.append(reward_kopecks)
    vals.append(check_id)
    con.execute(
        f"UPDATE campaign_checks SET {', '.join(fields)} WHERE id = ?",
        vals,
    )


def ledger_has(con: sqlite3.Connection, check_id: int, op_type: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM balance_ledger WHERE check_id = ? AND operation_type = ?",
        (check_id, op_type),
    ).fetchone()
    return row is not None


def add_ledger(
    con: sqlite3.Connection,
    *,
    user_id: int,
    check_id: int | None,
    operation_type: str,
    amount_kopecks: int,
    reason: str,
    admin_id: int | None = None,
) -> int:
    cur = con.execute(
        """INSERT INTO balance_ledger
           (user_id, check_id, operation_type, amount_kopecks, reason, admin_id, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (user_id, check_id, operation_type, amount_kopecks, reason, admin_id, _ts()),
    )
    return int(cur.lastrowid)


def user_balance_kopecks(con: sqlite3.Connection, user_id: int) -> int:
    row = con.execute(
        "SELECT COALESCE(SUM(amount_kopecks), 0) AS s FROM balance_ledger WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["s"] if row else 0)


def user_status_counts(con: sqlite3.Connection, user_id: int) -> dict[str, int]:
    rows = con.execute(
        """SELECT status, COUNT(*) AS c FROM campaign_checks
           WHERE user_id = ? GROUP BY status""",
        (user_id,),
    ).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[r["status"]] = int(r["c"])
    return out


def user_checks_recent(
    con: sqlite3.Connection, user_id: int, limit: int = 20
) -> list[sqlite3.Row]:
    return list(con.execute(
        """SELECT * FROM campaign_checks WHERE user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ))


def ledger_history(con: sqlite3.Connection, user_id: int, limit: int = 50) -> list[sqlite3.Row]:
    return list(con.execute(
        """SELECT * FROM balance_ledger WHERE user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ))


def ensure_payout_row(con: sqlite3.Connection, user_id: int) -> None:
    con.execute(
        """INSERT OR IGNORE INTO campaign_payouts
           (user_id, status, amount_kopecks, updated_at)
           VALUES (?, ?, 0, ?)""",
        (user_id, PAYOUT_PENDING, _ts()),
    )


def get_payout(con: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM campaign_payouts WHERE user_id = ?", (user_id,)
    ).fetchone()


def global_stats(con: sqlite3.Connection) -> dict[str, Any]:
    participants = con.execute(
        "SELECT COUNT(DISTINCT user_id) AS c FROM campaign_checks"
    ).fetchone()["c"]
    uploaded = con.execute("SELECT COUNT(*) AS c FROM campaign_checks").fetchone()["c"]
    by_status: dict[str, int] = {}
    for r in con.execute(
        "SELECT status, COUNT(*) AS c FROM campaign_checks GROUP BY status"
    ):
        by_status[r["status"]] = int(r["c"])
    by_bank = []
    for r in con.execute(
        """SELECT bank_key, COUNT(*) AS c FROM campaign_checks
           WHERE status = ? GROUP BY bank_key ORDER BY c DESC""",
        (STATUS_ACCEPTED,),
    ):
        by_bank.append((r["bank_key"] or "?", int(r["c"])))
    payout_total = con.execute(
        """SELECT COALESCE(SUM(amount_kopecks), 0) AS s FROM balance_ledger"""
    ).fetchone()["s"]
    # Only positive net balances of users with accepted credits
    nets = con.execute(
        """SELECT user_id, SUM(amount_kopecks) AS bal FROM balance_ledger
           GROUP BY user_id HAVING bal > 0"""
    ).fetchall()
    payout_owed = sum(int(r["bal"]) for r in nets)
    return {
        "participants": int(participants),
        "uploaded": int(uploaded),
        "by_status": by_status,
        "by_bank_accepted": by_bank,
        "ledger_sum": int(payout_total),
        "payout_owed": int(payout_owed),
        "reward_per_check": CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS,
    }


def balances_table(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            u.user_id AS user_id,
            (SELECT username FROM campaign_checks c2
             WHERE c2.user_id = u.user_id AND c2.username IS NOT NULL
             ORDER BY c2.id DESC LIMIT 1) AS username,
            (SELECT COUNT(*) FROM campaign_checks c3
             WHERE c3.user_id = u.user_id AND c3.status = 'accepted') AS accepted,
            COALESCE((SELECT SUM(amount_kopecks) FROM balance_ledger b
                      WHERE b.user_id = u.user_id), 0) AS balance
        FROM (SELECT DISTINCT user_id FROM campaign_checks
              UNION SELECT DISTINCT user_id FROM balance_ledger) u
        ORDER BY balance DESC, accepted DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def export_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    users = con.execute(
        "SELECT DISTINCT user_id FROM campaign_checks "
        "UNION SELECT DISTINCT user_id FROM balance_ledger"
    ).fetchall()
    out = []
    for u in users:
        uid = int(u["user_id"])
        counts = user_status_counts(con, uid)
        bal = user_balance_kopecks(con, uid)
        uname_row = con.execute(
            """SELECT username FROM campaign_checks WHERE user_id = ?
               AND username IS NOT NULL ORDER BY id DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        pout = get_payout(con, uid)
        out.append({
            "user_id": uid,
            "username": (uname_row["username"] if uname_row else "") or "",
            "uploaded_count": sum(counts.values()),
            "accepted_count": counts.get(STATUS_ACCEPTED, 0),
            "rejected_count": counts.get("rejected", 0),
            "fake_count": counts.get("fake", 0),
            "duplicate_count": counts.get("duplicate", 0),
            "balance": bal,
            "payout_status": (pout["status"] if pout else PAYOUT_PENDING),
        })
    out.sort(key=lambda x: (-x["balance"], -x["accepted_count"]))
    return out


def find_user_id(con: sqlite3.Connection, ref: str) -> int | None:
    ref = (ref or "").strip().lstrip("@")
    if ref.isdigit():
        return int(ref)
    row = con.execute(
        """SELECT user_id FROM campaign_checks
           WHERE lower(username) = lower(?) ORDER BY id DESC LIMIT 1""",
        (ref,),
    ).fetchone()
    return int(row["user_id"]) if row else None


# Initialize on import
init_db()
