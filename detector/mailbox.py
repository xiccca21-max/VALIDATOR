"""
Per-user inbound-mail address store.

Each Telegram user gets one short, unique nick. The same nick works on every
configured receiving domain, so the user is shown 3 addresses:

    <nick>@domain1   <nick>@domain2   <nick>@domain3

When a bank email arrives at <nick>@anything, the mail server looks the nick up
here to find which Telegram chat to deliver the verdict to.
"""

import os
import sqlite3
import time

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reputation.db")

# Adjective-free, unambiguous alphabet (no 0/o/1/l/i) for generated nicks.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _con():
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS mailboxes (
            nick      TEXT PRIMARY KEY,
            chat_id   INTEGER NOT NULL,
            created   REAL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_mb_chat ON mailboxes(chat_id)")
    return con


def _encode(n: int) -> str:
    if n == 0:
        return _ALPHABET[0]
    out = []
    base = len(_ALPHABET)
    while n:
        n, r = divmod(n, base)
        out.append(_ALPHABET[r])
    return "".join(reversed(out))


def _sanitize(username: str | None) -> str:
    """Turn a Telegram @username into a valid email local-part, or "" if unusable."""
    if not username:
        return ""
    s = "".join(ch for ch in username.lower() if ch.isalnum())
    return s if 2 <= len(s) <= 32 else ""


def _free(con, nick: str, chat_id: int) -> bool:
    row = con.execute("SELECT chat_id FROM mailboxes WHERE nick=?", (nick,)).fetchone()
    return row is None or int(row[0]) == int(chat_id)


def get_or_create(chat_id: int, username: str | None = None) -> str:
    """Return the user's stable nick, creating one on first use.

    Prefers the user's Telegram @username (so the address looks like the user's
    own nick, as competitors do); falls back to a short id-derived nick if no
    username is set or it is already taken by someone else.
    """
    desired = _sanitize(username)
    con = _con()
    try:
        row = con.execute(
            "SELECT nick FROM mailboxes WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row:
            current = row[0]
            # Migrate to the username-based nick if it differs and is free.
            if desired and desired != current and _free(con, desired, chat_id):
                con.execute("UPDATE mailboxes SET nick=? WHERE chat_id=?",
                            (desired, chat_id))
                con.commit()
                return desired
            return current

        if desired and _free(con, desired, chat_id):
            nick = desired
        else:
            base = desired or _encode(abs(int(chat_id)))
            nick = base
            suffix = 0
            while not _free(con, nick, chat_id):
                suffix += 1
                nick = f"{base}{_encode(suffix)}"
        con.execute(
            "INSERT INTO mailboxes(nick, chat_id, created) VALUES(?,?,?)",
            (nick, chat_id, time.time()),
        )
        con.commit()
        return nick
    finally:
        con.close()


def chat_for_nick(nick: str) -> int | None:
    """Resolve a received local-part back to a Telegram chat id."""
    nick = (nick or "").strip().lower()
    con = _con()
    try:
        row = con.execute(
            "SELECT chat_id FROM mailboxes WHERE nick=?", (nick,)
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        con.close()


def domains() -> list[str]:
    """Configured receiving domains, from MAIL_DOMAINS env (comma-separated)."""
    raw = os.getenv("MAIL_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def addresses_for(chat_id: int, username: str | None = None) -> list[str]:
    nick = get_or_create(chat_id, username)
    return [f"{nick}@{d}" for d in domains()]
