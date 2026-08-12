"""Campaign business logic: intake, accept, reject, reverse, payouts."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from . import db
from .config import (
    CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS,
    LEDGER_CREDIT,
    LEDGER_DEBIT,
    LEDGER_PAYOUT,
    LEDGER_REVERSE,
    PAYOUT_PAID,
    PAYOUT_PENDING,
    PAYOUT_REJECTED,
    REJECT_REASONS,
    STATUS_ACCEPTED,
    STATUS_DUPLICATE,
    STATUS_FAKE,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_REVERSED,
    STATUS_UNSUPPORTED,
    SUPPORTED_BANKS,
    campaign_has_ended,
    campaign_is_active,
    format_money_kopecks,
    now_msk,
)
from .identity import engine_meta, extract_identity

log = logging.getLogger(__name__)


def _reason(code: str, extra: str = "") -> tuple[str, str]:
    text = REJECT_REASONS.get(code, extra or code)
    if extra and code in ("manual", "terms") and extra != text:
        text = extra
    elif extra and code not in REJECT_REASONS:
        text = extra
    return code, text


def process_upload(
    *,
    user_id: int,
    username: str | None,
    pdf_bytes: bytes,
    bank_name: str,
    result: dict,
) -> dict[str, Any]:
    """
    Register a campaign check for an uploaded PDF.
    Always starts as pending, then applies automatic decisions.
    Returns {check_id, status, reason_text, reward_kopecks, notify}.
    """
    if not campaign_is_active():
        return {
            "check_id": None,
            "status": STATUS_UNSUPPORTED,
            "reason_code": "outside_window",
            "reason_text": REJECT_REASONS["outside_window"],
            "reward_kopecks": 0,
            "notify": False,
            "skipped": True,
        }

    if not pdf_bytes.startswith(b"%PDF-"):
        return _store_terminal(
            user_id, username, pdf_bytes, bank_name, result,
            STATUS_UNSUPPORTED, *_reason("not_pdf"),
        )

    identity = extract_identity(pdf_bytes, bank_name=bank_name)
    engine, decisive, raw_json = engine_meta(result)
    row = {
        "user_id": user_id,
        "username": username,
        "bank_key": identity["bank_key"],
        "bank_name": identity["bank_name"] or bank_name,
        "method": identity["method"],
        "file_sha256": identity["file_sha256"],
        "operation_identity_hash": identity["operation_identity_hash"],
        "operation_id": identity["operation_id"],
        "sbp_id": identity["sbp_id"],
        "transaction_number": identity["transaction_number"],
        "operation_datetime": identity["operation_datetime"],
        "amount_raw": identity["amount_raw"],
        "sender_mask": identity["sender_mask"],
        "recipient_identifier": identity["recipient_identifier"],
        "verdict": result.get("verdict"),
        "engine_version": engine,
        "decisive_flags": decisive,
        "validator_result_json": raw_json,
    }

    with db.db_tx() as con:
        # Uniqueness — first wins
        prior = db.find_by_hashes(
            con, identity["file_sha256"], identity["operation_identity_hash"] or None,
        )
        if prior is not None:
            try:
                check_id = db.insert_pending_check(con, {
                    **row,
                    # Avoid unique collision: blank hashes on duplicate row
                    "file_sha256": None,
                    "operation_identity_hash": None,
                })
            except Exception:
                # Extremely rare race — treat as skipped notify
                log.exception("duplicate insert failed")
                return {
                    "check_id": int(prior["id"]),
                    "status": STATUS_DUPLICATE,
                    "reason_code": "duplicate",
                    "reason_text": REJECT_REASONS["duplicate"],
                    "reward_kopecks": 0,
                    "notify": True,
                    "duplicate_of": int(prior["id"]),
                }
            db.update_check_status(
                con, check_id, STATUS_DUPLICATE,
                reason_code="duplicate",
                reason_text=REJECT_REASONS["duplicate"],
            )
            db.audit(
                con, admin_id=None, admin_username="system",
                action="auto_duplicate", target_user_id=user_id, check_id=check_id,
                detail=f"dup_of={prior['id']}",
            )
            return {
                "check_id": check_id,
                "status": STATUS_DUPLICATE,
                "reason_code": "duplicate",
                "reason_text": REJECT_REASONS["duplicate"],
                "reward_kopecks": 0,
                "notify": True,
                "duplicate_of": int(prior["id"]),
            }

        try:
            check_id = db.insert_pending_check(con, row)
        except Exception as exc:
            # Unique race with concurrent upload
            if "UNIQUE" in str(exc).upper():
                prior2 = db.find_by_hashes(
                    con, identity["file_sha256"], identity["operation_identity_hash"] or None,
                )
                return {
                    "check_id": int(prior2["id"]) if prior2 else None,
                    "status": STATUS_DUPLICATE,
                    "reason_code": "duplicate",
                    "reason_text": REJECT_REASONS["duplicate"],
                    "reward_kopecks": 0,
                    "notify": True,
                }
            raise

        # Auto pipeline from pending
        verdict = (result.get("verdict") or "").upper()
        bank_key = identity["bank_key"]

        if not bank_key or bank_key not in SUPPORTED_BANKS:
            return _finalize(
                con, check_id, user_id, STATUS_UNSUPPORTED, *_reason("unsupported"),
            )

        if verdict in ("ФЕЙК", "FAKE") or int(result.get("score") or 0) >= 60:
            return _finalize(con, check_id, user_id, STATUS_FAKE, *_reason("fake"))

        if verdict == "НЕИЗВЕСТНЫЙ ДОКУМЕНТ":
            return _finalize(
                con, check_id, user_id, STATUS_UNSUPPORTED, *_reason("unsupported"),
            )

        if not identity["operation_completed"]:
            return _finalize(
                con, check_id, user_id, STATUS_REJECTED, *_reason("failed_op"),
            )

        if identity["operation_date"] is not None and not identity["date_ok"]:
            return _finalize(con, check_id, user_id, STATUS_REJECTED, *_reason("date"))

        if verdict != "ЧИСТО":
            # Leave pending for manual review
            db.audit(
                con, admin_id=None, admin_username="system",
                action="auto_pending", target_user_id=user_id, check_id=check_id,
                detail=f"verdict={verdict}",
            )
            return {
                "check_id": check_id,
                "status": STATUS_PENDING,
                "reason_code": None,
                "reason_text": None,
                "reward_kopecks": 0,
                "notify": False,
            }

        # Auto-accept clean originals that passed all gates
        return _accept_locked(con, check_id, user_id, admin_id=None, reason="auto_accept")


def _finalize(
    con, check_id: int, user_id: int, status: str, code: str, text: str,
) -> dict[str, Any]:
    db.update_check_status(
        con, check_id, status, reason_code=code, reason_text=text,
    )
    db.audit(
        con, admin_id=None, admin_username="system",
        action=f"auto_{status}", target_user_id=user_id, check_id=check_id,
        detail=text,
    )
    return {
        "check_id": check_id,
        "status": status,
        "reason_code": code,
        "reason_text": text,
        "reward_kopecks": 0,
        "notify": True,
    }


def _store_terminal(
    user_id, username, pdf_bytes, bank_name, result, status, code, text,
) -> dict[str, Any]:
    identity = extract_identity(pdf_bytes, bank_name=bank_name) if pdf_bytes else {}
    engine, decisive, raw_json = engine_meta(result or {})
    with db.db_tx() as con:
        check_id = db.insert_pending_check(con, {
            "user_id": user_id,
            "username": username,
            "bank_key": identity.get("bank_key"),
            "bank_name": bank_name,
            "method": identity.get("method"),
            "file_sha256": None,  # avoid unique on junk
            "operation_identity_hash": None,
            "verdict": (result or {}).get("verdict"),
            "engine_version": engine,
            "decisive_flags": decisive,
            "validator_result_json": raw_json,
        })
        return _finalize(con, check_id, user_id, status, code, text)


def _accept_locked(
    con, check_id: int, user_id: int, *, admin_id: int | None, reason: str,
) -> dict[str, Any]:
    row = db.get_check(con, check_id)
    if not row:
        return {"ok": False, "error": "check not found"}
    if row["status"] == STATUS_ACCEPTED and db.ledger_has(con, check_id, LEDGER_CREDIT):
        # Idempotent
        return {
            "check_id": check_id,
            "status": STATUS_ACCEPTED,
            "reward_kopecks": int(row["reward_kopecks"] or 0),
            "notify": False,
            "idempotent": True,
        }
    if row["status"] not in (STATUS_PENDING, STATUS_REJECTED, STATUS_UNSUPPORTED):
        if row["status"] == STATUS_ACCEPTED:
            return {
                "check_id": check_id,
                "status": STATUS_ACCEPTED,
                "reward_kopecks": int(row["reward_kopecks"] or 0),
                "notify": False,
                "idempotent": True,
            }
        return {"ok": False, "error": f"cannot accept from {row['status']}"}

    reward = CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS
    if not db.ledger_has(con, check_id, LEDGER_CREDIT):
        db.add_ledger(
            con,
            user_id=user_id,
            check_id=check_id,
            operation_type=LEDGER_CREDIT,
            amount_kopecks=reward,
            reason=reason,
            admin_id=admin_id,
        )
    db.update_check_status(
        con, check_id, STATUS_ACCEPTED, reward_kopecks=reward, moderator_id=admin_id,
    )
    db.ensure_payout_row(con, user_id)
    db.audit(
        con, admin_id=admin_id, admin_username=None,
        action="accept", target_user_id=user_id, check_id=check_id, detail=reason,
    )
    return {
        "check_id": check_id,
        "status": STATUS_ACCEPTED,
        "reward_kopecks": reward,
        "reason_code": None,
        "reason_text": None,
        "notify": True,
        "ok": True,
    }


def accept_check(check_id: int, admin_id: int, admin_username: str | None = None) -> dict:
    with db.db_tx() as con:
        row = db.get_check(con, check_id)
        if not row:
            return {"ok": False, "error": "чек не найден"}
        out = _accept_locked(
            con, check_id, int(row["user_id"]),
            admin_id=admin_id, reason="manual_accept",
        )
        if out.get("ok") is False and "error" in out:
            return out
        db.audit(
            con, admin_id=admin_id, admin_username=admin_username,
            action="admin_accept", target_user_id=int(row["user_id"]),
            check_id=check_id, detail="manual_accept",
        )
        out["user_id"] = int(row["user_id"])
        out["ok"] = True
        return out


def _reverse_credit_if_any(
    con, check_id: int, user_id: int, *, admin_id: int, reason: str,
) -> bool:
    if not db.ledger_has(con, check_id, LEDGER_CREDIT):
        return False
    if db.ledger_has(con, check_id, LEDGER_REVERSE):
        return False
    credit = con.execute(
        """SELECT amount_kopecks FROM balance_ledger
           WHERE check_id = ? AND operation_type = ?""",
        (check_id, LEDGER_CREDIT),
    ).fetchone()
    amt = int(credit["amount_kopecks"]) if credit else CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS
    db.add_ledger(
        con,
        user_id=user_id,
        check_id=check_id,
        operation_type=LEDGER_REVERSE,
        amount_kopecks=-abs(amt),
        reason=reason,
        admin_id=admin_id,
    )
    return True


def reject_check(
    check_id: int, admin_id: int, reason: str, admin_username: str | None = None,
) -> dict:
    with db.db_tx() as con:
        row = db.get_check(con, check_id)
        if not row:
            return {"ok": False, "error": "чек не найден"}
        uid = int(row["user_id"])
        reversed_credit = False
        new_status = STATUS_REJECTED
        if row["status"] == STATUS_ACCEPTED:
            reversed_credit = _reverse_credit_if_any(
                con, check_id, uid, admin_id=admin_id, reason=reason or "reject",
            )
            new_status = STATUS_REVERSED if reversed_credit else STATUS_REJECTED
        code, text = _reason("manual", reason or REJECT_REASONS["manual"])
        db.update_check_status(
            con, check_id, new_status,
            reason_code=code, reason_text=text, moderator_id=admin_id,
            reward_kopecks=0 if reversed_credit else None,
        )
        db.audit(
            con, admin_id=admin_id, admin_username=admin_username,
            action="admin_reject", target_user_id=uid, check_id=check_id, detail=text,
        )
        return {
            "ok": True,
            "check_id": check_id,
            "user_id": uid,
            "status": new_status,
            "reversed": reversed_credit,
            "reason_text": text,
        }


def fake_check(
    check_id: int, admin_id: int, reason: str, admin_username: str | None = None,
) -> dict:
    with db.db_tx() as con:
        row = db.get_check(con, check_id)
        if not row:
            return {"ok": False, "error": "чек не найден"}
        uid = int(row["user_id"])
        reversed_credit = False
        if row["status"] == STATUS_ACCEPTED:
            reversed_credit = _reverse_credit_if_any(
                con, check_id, uid, admin_id=admin_id,
                reason=reason or "fake after accept",
            )
        text = reason or REJECT_REASONS["fake"]
        final = STATUS_REVERSED if reversed_credit else STATUS_FAKE
        # If never accepted, mark fake; if reversed from accept, status reversed
        # but also record fake reason — use fake if not reversed
        if not reversed_credit:
            final = STATUS_FAKE
        db.update_check_status(
            con, check_id, final,
            reason_code="fake", reason_text=text, moderator_id=admin_id,
            reward_kopecks=0 if reversed_credit else None,
        )
        db.audit(
            con, admin_id=admin_id, admin_username=admin_username,
            action="admin_fake", target_user_id=uid, check_id=check_id, detail=text,
        )
        return {
            "ok": True,
            "check_id": check_id,
            "user_id": uid,
            "status": final,
            "reversed": reversed_credit,
            "reason_text": text,
        }


def adjust_balance(
    user_id: int, amount_kopecks: int, reason: str, admin_id: int,
    admin_username: str | None = None,
) -> dict:
    if not reason or not reason.strip():
        return {"ok": False, "error": "нужна причина"}
    if amount_kopecks == 0:
        return {"ok": False, "error": "сумма не может быть 0"}
    with db.db_tx() as con:
        db.add_ledger(
            con,
            user_id=user_id,
            check_id=None,
            operation_type=LEDGER_DEBIT if amount_kopecks < 0 else LEDGER_CREDIT,
            amount_kopecks=amount_kopecks,
            reason=reason.strip(),
            admin_id=admin_id,
        )
        # UNIQUE(check_id, operation_type) — check_id NULL allows multiple adjusts
        db.ensure_payout_row(con, user_id)
        bal = db.user_balance_kopecks(con, user_id)
        db.audit(
            con, admin_id=admin_id, admin_username=admin_username,
            action="adjust_balance", target_user_id=user_id,
            detail=f"{amount_kopecks}:{reason}",
        )
        return {"ok": True, "user_id": user_id, "balance": bal}


def payout_mark(
    user_id: int, status: str, admin_id: int,
    reason: str = "", admin_username: str | None = None,
) -> dict:
    status = status.lower().strip()
    if status not in (PAYOUT_PAID, PAYOUT_REJECTED):
        return {"ok": False, "error": "status: paid|rejected"}
    with db.db_tx() as con:
        db.ensure_payout_row(con, user_id)
        row = db.get_payout(con, user_id)
        if row and row["status"] == PAYOUT_PAID:
            return {"ok": False, "error": "уже выплачено — повторная выплата запрещена"}
        bal = db.user_balance_kopecks(con, user_id)
        if status == PAYOUT_PAID:
            if bal <= 0:
                return {"ok": False, "error": "нечего выплачивать"}
            # Idempotent payout ledger: one payout row per user via unique? use check_id=None
            # Prevent double payout ledger by checking existing payout ledger sum
            existing = con.execute(
                """SELECT COALESCE(SUM(amount_kopecks),0) AS s FROM balance_ledger
                   WHERE user_id = ? AND operation_type = ?""",
                (user_id, LEDGER_PAYOUT),
            ).fetchone()
            if int(existing["s"]) != 0:
                return {"ok": False, "error": "payout уже есть в журнале"}
            db.add_ledger(
                con,
                user_id=user_id,
                check_id=None,
                operation_type=LEDGER_PAYOUT,
                amount_kopecks=-bal,
                reason=reason or "payout",
                admin_id=admin_id,
            )
            con.execute(
                """UPDATE campaign_payouts
                   SET status=?, amount_kopecks=?, reason=?, admin_id=?,
                       paid_at=?, updated_at=?
                   WHERE user_id=?""",
                (PAYOUT_PAID, bal, reason or "paid", admin_id,
                 now_msk().strftime("%Y-%m-%d %H:%M:%S"),
                 now_msk().strftime("%Y-%m-%d %H:%M:%S"), user_id),
            )
        else:
            con.execute(
                """UPDATE campaign_payouts
                   SET status=?, reason=?, admin_id=?, updated_at=?
                   WHERE user_id=?""",
                (PAYOUT_REJECTED, reason or "rejected", admin_id,
                 now_msk().strftime("%Y-%m-%d %H:%M:%S"), user_id),
            )
        db.audit(
            con, admin_id=admin_id, admin_username=admin_username,
            action=f"payout_{status}", target_user_id=user_id, detail=reason,
        )
        return {"ok": True, "user_id": user_id, "status": status, "amount": bal if status == PAYOUT_PAID else 0}


def profile_snapshot(user_id: int) -> dict[str, Any]:
    with db.db_tx() as con:
        counts = db.user_status_counts(con, user_id)
        bal = db.user_balance_kopecks(con, user_id)
        pout = db.get_payout(con, user_id)
        uploaded = sum(counts.values())
        return {
            "uploaded": uploaded,
            "pending": counts.get(STATUS_PENDING, 0),
            "accepted": counts.get(STATUS_ACCEPTED, 0),
            "rejected": counts.get(STATUS_REJECTED, 0),
            "duplicate": counts.get(STATUS_DUPLICATE, 0),
            "fake": counts.get(STATUS_FAKE, 0),
            "unsupported": counts.get(STATUS_UNSUPPORTED, 0),
            "reversed": counts.get(STATUS_REVERSED, 0),
            "balance_kopecks": bal,
            "balance_text": format_money_kopecks(bal),
            "payout_status": (pout["status"] if pout else PAYOUT_PENDING),
            "campaign_ended": campaign_has_ended(),
        }


def recent_checks(user_id: int, limit: int = 15) -> list[dict]:
    with db.db_tx() as con:
        rows = db.user_checks_recent(con, user_id, limit)
        return [dict(r) for r in rows]


def get_check(check_id: int) -> dict | None:
    with db.db_tx() as con:
        row = db.get_check(con, check_id)
        return dict(row) if row else None


def user_admin_view(ref: str) -> dict | None:
    with db.db_tx() as con:
        uid = db.find_user_id(con, ref)
        if uid is None:
            return None
        counts = db.user_status_counts(con, uid)
        bal = db.user_balance_kopecks(con, uid)
        hist = [dict(r) for r in db.ledger_history(con, uid, 30)]
        uname = None
        r = con.execute(
            """SELECT username FROM campaign_checks WHERE user_id=?
               AND username IS NOT NULL ORDER BY id DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if r:
            uname = r["username"]
        return {
            "user_id": uid,
            "username": uname,
            "counts": counts,
            "uploaded": sum(counts.values()),
            "accepted": counts.get(STATUS_ACCEPTED, 0),
            "fake": counts.get(STATUS_FAKE, 0),
            "duplicate": counts.get(STATUS_DUPLICATE, 0),
            "balance": bal,
            "ledger": hist,
        }


def campaign_stats() -> dict:
    with db.db_tx() as con:
        return db.global_stats(con)


def campaign_balances() -> list[dict]:
    with db.db_tx() as con:
        return db.balances_table(con)


def export_csv() -> str:
    with db.db_tx() as con:
        rows = db.export_rows(con)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[
        "user_id", "username", "uploaded_count", "accepted_count",
        "rejected_count", "fake_count", "duplicate_count", "balance", "payout_status",
    ])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
