"""Bot usage analytics — persistent SQLite log for admin dashboard."""

from __future__ import annotations

import html
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics.db")
_MSK = timedelta(hours=3)


def _today_msk() -> str:
    return (datetime.now(timezone.utc) + _MSK).date().isoformat()


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            first_seen  REAL NOT NULL,
            last_seen   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_active (
            day     TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (day, user_id)
        );
        CREATE TABLE IF NOT EXISTS checks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            day         TEXT NOT NULL,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            first_name  TEXT,
            chat_type   TEXT,
            bank        TEXT,
            verdict     TEXT,
            filename    TEXT,
            score       INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_checks_day ON checks(day);
        CREATE INDEX IF NOT EXISTS idx_checks_ts ON checks(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_checks_user ON checks(user_id);
    """)
    con.commit()
    return con


def _user_label(username: str | None, first_name: str | None, user_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return f"id:{user_id}"


def touch_user(
    user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    if not user_id:
        return
    now = time.time()
    day = _today_msk()
    con = _con()
    try:
        row = con.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            con.execute(
                """UPDATE users SET username=?, first_name=?, last_name=?,
                   last_seen=? WHERE user_id=?""",
                (username, first_name, last_name, now, user_id),
            )
        else:
            con.execute(
                """INSERT INTO users (user_id, username, first_name, last_name,
                   first_seen, last_seen) VALUES (?,?,?,?,?,?)""",
                (user_id, username, first_name, last_name, now, now),
            )
        con.execute(
            "INSERT OR IGNORE INTO daily_active (day, user_id) VALUES (?,?)",
            (day, user_id),
        )
        con.commit()
    finally:
        con.close()


def log_check(
    user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    chat_type: str | None = None,
    bank: str | None = None,
    verdict: str | None = None,
    filename: str | None = None,
    score: int = 0,
) -> None:
    if not user_id:
        return
    touch_user(user_id, username=username, first_name=first_name, last_name=last_name)
    now = time.time()
    day = _today_msk()
    con = _con()
    try:
        con.execute(
            """INSERT INTO checks
               (ts, day, user_id, username, first_name, chat_type, bank, verdict,
                filename, score)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                now, day, user_id, username, first_name, chat_type,
                bank, verdict, filename, score,
            ),
        )
        con.commit()
    finally:
        con.close()


def _fmt_time(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) + _MSK
    return dt.strftime("%H:%M")


def format_dashboard_html(*, recent_limit: int = 20, today_users_limit: int = 30) -> str:
    day = _today_msk()
    con = _con()
    try:
        total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        users_today = con.execute(
            "SELECT COUNT(*) FROM daily_active WHERE day = ?", (day,)
        ).fetchone()[0]
        checks_today = con.execute(
            "SELECT COUNT(*) FROM checks WHERE day = ?", (day,)
        ).fetchone()[0]
        checks_total = con.execute("SELECT COUNT(*) FROM checks").fetchone()[0]
        fakes_today = con.execute(
            "SELECT COUNT(*) FROM checks WHERE day = ? AND verdict = 'ФЕЙК'", (day,)
        ).fetchone()[0]
        fakes_total = con.execute(
            "SELECT COUNT(*) FROM checks WHERE verdict = 'ФЕЙК'"
        ).fetchone()[0]

        today_rows = con.execute(
            """SELECT u.user_id, u.username, u.first_name,
                      (SELECT COUNT(*) FROM checks c
                       WHERE c.user_id = u.user_id AND c.day = ?) AS checks
               FROM daily_active d
               JOIN users u ON u.user_id = d.user_id
               WHERE d.day = ?
               ORDER BY u.last_seen DESC
               LIMIT ?""",
            (day, day, today_users_limit),
        ).fetchall()

        recent = con.execute(
            """SELECT ts, user_id, username, first_name, bank, verdict, filename, chat_type
               FROM checks ORDER BY ts DESC LIMIT ?""",
            (recent_limit,),
        ).fetchall()

        by_bank = con.execute(
            """SELECT bank, COUNT(*) AS cnt FROM checks
               WHERE day = ? AND bank IS NOT NULL AND bank != ''
               GROUP BY bank ORDER BY cnt DESC LIMIT 8""",
            (day,),
        ).fetchall()
    finally:
        con.close()

    lines = [
        f"📊 <b>Статистика бота</b> · {html.escape(day)}",
        "",
        f"👥 Всего пользователей: <b>{total_users}</b>",
        f"🟢 Заходили сегодня: <b>{users_today}</b>",
        f"📄 Проверок сегодня: <b>{checks_today}</b> (фейков: {fakes_today})",
        f"📄 Проверок всего: <b>{checks_total}</b> (фейков: {fakes_total})",
    ]

    if by_bank:
        lines += ["", "<b>Банки сегодня:</b>"]
        for row in by_bank:
            lines.append(f"• {html.escape(row['bank'] or '?')}: {row['cnt']}")

    if today_rows:
        lines += ["", f"<b>Сегодня заходили ({users_today}):</b>"]
        for row in today_rows:
            label = html.escape(_user_label(row["username"], row["first_name"], row["user_id"]))
            chk = row["checks"] or 0
            suffix = f" — {chk} пров." if chk else ""
            lines.append(f"• {label}{suffix}")

    if recent:
        lines += ["", "<b>Последние проверки:</b>"]
        for row in recent:
            label = html.escape(_user_label(row["username"], row["first_name"], row["user_id"]))
            bank = html.escape(row["bank"] or "—")
            verdict = html.escape(row["verdict"] or "—")
            fname = html.escape((row["filename"] or "—")[:40])
            chat = html.escape(row["chat_type"] or "")
            chat_tag = f" [{chat}]" if chat and chat != "private" else ""
            lines.append(
                f"• {_fmt_time(row['ts'])} {label}{chat_tag} · {bank} · "
                f"<b>{verdict}</b> · <code>{fname}</code>"
            )

    text = "\n".join(lines)
    if len(text) > 3900:
        return text[:3900] + "\n…"
    return text
