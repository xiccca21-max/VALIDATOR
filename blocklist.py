"""Persistent user blocklist for the Telegram bot."""

from __future__ import annotations

import json
import pathlib
import threading

_PATH = pathlib.Path(__file__).with_name("data") / "blocked_users.json"
_LOCK = threading.Lock()
_DEFAULT = {"usernames": ["p2plogger"], "user_ids": []}


def _load() -> dict:
    with _LOCK:
        if not _PATH.exists():
            return dict(_DEFAULT)
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            return dict(_DEFAULT)
        data.setdefault("usernames", [])
        data.setdefault("user_ids", [])
        return data


def _save(data: dict) -> None:
    with _LOCK:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def is_blocked(user_id: int = 0, username: str | None = None) -> bool:
    data = _load()
    if user_id and user_id in data["user_ids"]:
        return True
    uname = (username or "").lower().lstrip("@")
    return bool(uname and uname in {u.lower() for u in data["usernames"]})


def block_user(*, user_id: int = 0, username: str | None = None) -> str:
    data = _load()
    added: list[str] = []
    if user_id and user_id not in data["user_ids"]:
        data["user_ids"].append(user_id)
        added.append(f"id:{user_id}")
    uname = (username or "").lower().lstrip("@")
    if uname:
        existing = {u.lower() for u in data["usernames"]}
        if uname not in existing:
            data["usernames"].append(uname)
            added.append(f"@{uname}")
    if not added:
        return "Уже в блоклисте."
    _save(data)
    return "Заблокирован: " + ", ".join(added)


def unblock_user(*, user_id: int = 0, username: str | None = None) -> str:
    data = _load()
    removed: list[str] = []
    if user_id and user_id in data["user_ids"]:
        data["user_ids"].remove(user_id)
        removed.append(f"id:{user_id}")
    uname = (username or "").lower().lstrip("@")
    if uname:
        before = list(data["usernames"])
        data["usernames"] = [u for u in before if u.lower() != uname]
        if len(data["usernames"]) < len(before):
            removed.append(f"@{uname}")
    if not removed:
        return "Не найден в блоклисте."
    _save(data)
    return "Разблокирован: " + ", ".join(removed)


def list_blocked() -> str:
    data = _load()
    names = [f"@{u}" for u in data["usernames"]]
    ids = [f"id:{i}" for i in data["user_ids"]]
    items = names + ids
    if not items:
        return "Блоклист пуст."
    return "Заблокированы:\n" + "\n".join(f"• {x}" for x in items)
