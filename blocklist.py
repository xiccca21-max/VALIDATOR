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


def _norm_username(username: str | None) -> str:
    return (username or "").lower().lstrip("@").strip()


def _ensure_entries(data: dict) -> dict:
    data.setdefault("usernames", [])
    data.setdefault("user_ids", [])
    entries = data.setdefault("entries", {})
    for uname in data["usernames"]:
        key = "u:" + _norm_username(uname)
        entries.setdefault(key, {"username": _norm_username(uname), "user_id": 0, "reason": ""})
    for uid in data["user_ids"]:
        key = f"id:{int(uid)}"
        entries.setdefault(key, {"username": "", "user_id": int(uid), "reason": ""})
    return data


def is_blocked(user_id: int = 0, username: str | None = None) -> bool:
    data = _ensure_entries(_load())
    if user_id and user_id in data["user_ids"]:
        return True
    uname = _norm_username(username)
    return bool(uname and uname in {_norm_username(u) for u in data["usernames"]})


def block_reason(user_id: int = 0, username: str | None = None) -> str:
    data = _ensure_entries(_load())
    uname = _norm_username(username)
    reason = ""
    if uname:
        ent = data["entries"].get("u:" + uname) or {}
        reason = str(ent.get("reason") or "")
    if user_id:
        ent = data["entries"].get(f"id:{int(user_id)}") or {}
        if ent.get("reason"):
            reason = str(ent["reason"])
    return reason.strip()


def block_user(*, user_id: int = 0, username: str | None = None, reason: str = "") -> str:
    uname = _norm_username(username)
    if uname in {"kronlead", "acterichee"}:
        return "Этого пользователя блокировать нельзя."
    if not user_id and not uname:
        return "Укажи @username или id."
    data = _ensure_entries(_load())
    reason = (reason or "").strip()
    labels: list[str] = []
    if user_id:
        uid = int(user_id)
        if uid not in data["user_ids"]:
            data["user_ids"].append(uid)
        data["entries"][f"id:{uid}"] = {
            "username": uname,
            "user_id": uid,
            "reason": reason,
        }
        labels.append(f"id:{uid}")
    if uname:
        existing = {_norm_username(u) for u in data["usernames"]}
        if uname not in existing:
            data["usernames"].append(uname)
        data["entries"]["u:" + uname] = {
            "username": uname,
            "user_id": int(user_id or 0),
            "reason": reason,
        }
        labels.append(f"@{uname}")
    _save(data)
    tail = f"\nПричина: {reason}" if reason else ""
    return "Заблокирован: " + ", ".join(labels) + tail


def unblock_user(*, user_id: int = 0, username: str | None = None) -> str:
    data = _ensure_entries(_load())
    removed: list[str] = []
    if user_id and user_id in data["user_ids"]:
        data["user_ids"].remove(user_id)
        data["entries"].pop(f"id:{int(user_id)}", None)
        removed.append(f"id:{user_id}")
    uname = _norm_username(username)
    if uname:
        before = list(data["usernames"])
        data["usernames"] = [u for u in before if _norm_username(u) != uname]
        data["entries"].pop("u:" + uname, None)
        if len(data["usernames"]) < len(before):
            removed.append(f"@{uname}")
    if not removed:
        return "Не найден в блоклисте."
    _save(data)
    return "Разблокирован: " + ", ".join(removed)


def list_blocked() -> str:
    data = _ensure_entries(_load())
    lines: list[str] = []
    seen: set[str] = set()
    for uname in data["usernames"]:
        key = "u:" + _norm_username(uname)
        if key in seen:
            continue
        seen.add(key)
        reason = str((data["entries"].get(key) or {}).get("reason") or "").strip()
        line = f"• @{_norm_username(uname)}"
        if reason:
            line += f" — {reason}"
        lines.append(line)
    for uid in data["user_ids"]:
        key = f"id:{int(uid)}"
        ent = data["entries"].get(key) or {}
        if ent.get("username") and ("u:" + _norm_username(ent["username"])) in seen:
            continue
        reason = str(ent.get("reason") or "").strip()
        line = f"• id:{int(uid)}"
        if reason:
            line += f" — {reason}"
        lines.append(line)
    if not lines:
        return "Блоклист пуст."
    return "Заблокированы:\n" + "\n".join(lines)
