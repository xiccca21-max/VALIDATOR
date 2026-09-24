"""Persistent registry of who checked which receipt and when.

Every PDF that passes through the bot is recorded with the checking user's
username and a timestamp. When the same receipt shows up again (same file, or
the same underlying bank operation re-exported / re-saved), the caller gets the
list of previous checks to show under the verdict.

Matching works on two keys:
  * ``file_hash``  — SHA-256 of the bytes (exact same file);
  * ``op_key``     — operation identity: a strong operation id extracted from
    the text, combined with the printed date/time and amount. This survives a
    fresh export from the bank app. Weak fallbacks (bare long digit runs, which
    could be a receiver account shared by many payments) are deliberately NOT
    used, so two different payments to the same wallet never collide.

The verdict is intentionally not stored/shown here — only who and when.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sqlite3
import threading
import time

from detector import reputation

_PATH = pathlib.Path(__file__).with_name("data") / "check_history.db"
_LOCK = threading.Lock()
_MSK = datetime.timezone(datetime.timedelta(hours=3))

MAX_SHOWN = 10

# Accounts whose checks are never recorded and never shown in the history.
HIDDEN_USERNAMES = frozenset({"kronlead"})

_DATE_TIME_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})[\s,]+(\d{2}:\d{2})")
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_]{7,}")


def _con() -> sqlite3.Connection:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_PATH), timeout=10)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash  TEXT NOT NULL,
            op_key     TEXT,
            user_id    INTEGER,
            username   TEXT,
            bank       TEXT,
            checked_at REAL NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_checks_hash ON checks(file_hash)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_checks_op ON checks(op_key)")
    con.commit()
    return con


# ── operation identity ────────────────────────────────────────────────────────

def _strong_opid(text: str) -> str | None:
    """Operation id via strong strategies only (no bare digit-run fallback)."""
    t = text or ""
    sbp = reputation.extract_opid(t)
    if sbp and sbp.endswith(reputation.TBANK_SBP_SUFFIX):
        return sbp.upper()
    mo = re.search(r"po-[0-9a-fA-F\-]{16,}", t)
    if mo:
        return mo.group(0).lower()
    low = t.lower()
    for label in reputation._ID_LABELS:
        pos = low.find(label)
        if pos < 0:
            continue
        window = t[pos + len(label): pos + len(label) + 80]
        m = _ID_TOKEN_RE.search(window)
        if m and any(c.isdigit() for c in m.group(0)):
            return m.group(0)
    return None


def operation_key(text: str, parsed: dict | None) -> str | None:
    """Stable identity of the bank operation, or None if not extractable."""
    opid = _strong_opid(text)
    if not opid:
        return None
    dm = _DATE_TIME_RE.search(text or "")
    when = f"{dm.group(1)} {dm.group(2)}" if dm else ""
    amount = re.sub(r"\D", "", str((parsed or {}).get("amount") or ""))
    return f"{opid}|{when}|{amount}"


# ── record / query ────────────────────────────────────────────────────────────

def record(
    pdf_bytes: bytes,
    text: str,
    parsed: dict | None,
    *,
    user_id: int,
    username: str | None,
    bank: str = "",
) -> list[dict]:
    """Store this check and return all PREVIOUS checks of the same receipt.

    Each returned entry: {"checked_at": float, "user_id": int, "username": str}.
    Ordered oldest first. Empty list on first sight.
    """
    fh = reputation.file_hash(pdf_bytes)
    op_key = operation_key(text, parsed)
    uname = (username or "").lstrip("@").strip()
    hidden_checker = is_hidden(uname)
    now = time.time()
    with _LOCK:
        con = _con()
        try:
            if op_key:
                rows = con.execute(
                    "SELECT checked_at, user_id, username FROM checks"
                    " WHERE file_hash=? OR op_key=? ORDER BY checked_at ASC, id ASC",
                    (fh, op_key),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT checked_at, user_id, username FROM checks"
                    " WHERE file_hash=? ORDER BY checked_at ASC, id ASC",
                    (fh,),
                ).fetchall()
            if not hidden_checker:
                con.execute(
                    "INSERT INTO checks(file_hash, op_key, user_id, username, bank, checked_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (fh, op_key, int(user_id or 0), uname, bank or "", now),
                )
                con.commit()
        finally:
            con.close()
    return [
        {"checked_at": float(ts), "user_id": int(uid or 0), "username": un or ""}
        for ts, uid, un in rows
        if not is_hidden(un)
    ]


def is_hidden(username: str | None) -> bool:
    return (username or "").lstrip("@").strip().lower() in HIDDEN_USERNAMES


# ── presentation ──────────────────────────────────────────────────────────────

def _who(entry: dict) -> str:
    if entry.get("username"):
        return "@" + entry["username"]
    return f"id:{entry.get('user_id') or 0}"


def _when(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=_MSK).strftime("%d.%m.%Y %H:%M")


def format_history(prior: list[dict]) -> str:
    """Plain-text block for the bot message. Empty string if never seen before."""
    prior = [e for e in prior if not is_hidden(e.get("username"))]
    if not prior:
        return ""
    shown = prior[-MAX_SHOWN:]
    hidden = len(prior) - len(shown)
    lines = ["Чек ранее проверялся:"]
    if hidden > 0:
        lines.append(f"- … и ещё {hidden} раз ранее")
    lines += [f"- {_when(e['checked_at'])}, {_who(e)}" for e in shown]
    return "\n".join(lines)
