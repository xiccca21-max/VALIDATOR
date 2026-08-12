# -*- coding: utf-8 -*-
"""Watch Kron → @proton_pdf_bot: download PDFs, local route(), emit wake lines.

Prints AGENT_DEFENDER_CASE JSON when bot/local is CLEAN/UNKNOWN or mismatch.
Session: tools/.tg_defender_session (Kron).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
_ZAP_CANDIDATES = (
    Path(r"C:\Users\fanis\OneDrive\Desktop\запас альфа рабочая\tools"),
    Path(r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26\tools"),
)
for _zap in _ZAP_CANDIDATES:
    if (_zap / "tg_check_pdf.py").exists():
        sys.path.insert(0, str(_zap))
        break
sys.path.insert(0, str(_ROOT))

from tg_check_pdf import _load_env  # noqa: E402
from tg_client import make_client, ensure_login  # noqa: E402

_INBOX = _ROOT / "output" / "defender_inbox"
_STATE = _ROOT / "output" / "defender_seen_ids.json"
_LOG = _ROOT / "output" / "defender_watch.log"
_BOT = "proton_pdf_bot"
_POLL_SEC = 8
_last_deploy_ts = 0.0
# msg_id -> consecutive OTHER/no-verdict waits (avoid infinite spin on stuck replies)
_other_waits: dict[int, int] = {}
_OTHER_WAIT_MAX = 8


def _log_line(line: str) -> None:
    """Mirror wake lines to defender_watch.log for night_clean_streak."""
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_seen() -> set[int]:
    if not _STATE.exists():
        return set()
    try:
        return set(json.loads(_STATE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen: set[int]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(sorted(seen)[-800:]), encoding="utf-8")


def _bot_verdict(text: str) -> str:
    t = text or ""
    # CLEAN first: policy blurb contains «не является подделкой» and must not
    # be misread as FAKE (was hiding live proton CLEANs as bot=FAKE).
    if re.search(r"✅\s*ЧИСТО", t) or re.search(r"(?m)^\s*ЧИСТО\s*$", t):
        return "CLEAN"
    if "ОРИГИНАЛ" in t and "ФЕЙК" not in t and "❌" not in t:
        return "CLEAN"
    if "ФЕЙК" in t or "❌" in t:
        return "FAKE"
    if re.search(r"(?<![а-яА-ЯёЁ])Подделка(?![а-яА-ЯёЁ])", t):
        return "FAKE"
    if "НЕИЗВЕСТ" in t:
        return "UNKNOWN"
    if "ЧИСТО" in t:
        return "CLEAN"
    return "OTHER"


def _flag_codes(result: dict) -> list[str]:
    out: list[str] = []
    for f in result.get("flags") or []:
        if isinstance(f, dict):
            out.append(str(f.get("code") or f.get("detail") or "")[:80])
        else:
            s = str(f)
            m = re.search(r"\[([A-Z0-9_\-]+)\]", s)
            out.append(m.group(1) if m else s[:80])
    return out[:12]


def _auto_harden(pdf_bytes: bytes, bank: str, path: Path, *, caption: str = "") -> list[str]:
    """Novelty font pins disabled — catch via structural HARD only.

    Auto-pinning FontFile2 / F2 glyf-loca caused genuine FPs (e.g. Sber
    ba725e456bf8e2cf on 1944 (2).pdf). Keep the hook for future structural
    hardeners, but do not write pin sidecars.
    """
    return ["skip_pin:novelty_disabled"]


def _deploy_pins() -> None:
    global _last_deploy_ts
    now = time.time()
    # Hard throttle — frequent restarts caused Telegram ServerDisconnectedError
    # mid-download for live checks.
    if now - _last_deploy_ts < 120:
        print("AGENT_DEFENDER_DEPLOY skip_throttle", flush=True)
        return
    _last_deploy_ts = now
    try:
        import subprocess
        # JSON sidecars hot-reload in-process — never restart bot for pins.
        cmd = [
            sys.executable, "-u", str(_ROOT / "tools" / "deploy_validator_sync.py"),
            "--no-restart",
            "detector/tbank_v6/k_font_002_extra.json",
            "detector/sber_v2/known_fake_fontfile2_extra.json",
        ]
        print("AGENT_DEFENDER_DEPLOY start_no_restart", flush=True)
        subprocess.run(cmd, cwd=str(_ROOT), check=False, timeout=120)
        print("AGENT_DEFENDER_DEPLOY done", flush=True)
    except Exception as exc:
        print(f"AGENT_DEFENDER_ERR deploy: {exc}", flush=True)


async def _handle_pdf(client, pdf_msg, reply_msg, seen: set[int]) -> None:
    from detector import route

    name = "doc.pdf"
    for a in (pdf_msg.document.attributes or []):
        if getattr(a, "file_name", None):
            name = a.file_name
            break
    _INBOX.mkdir(parents=True, exist_ok=True)
    path = _INBOX / f"{pdf_msg.id}_{name}"
    if not path.exists():
        await client.download_media(pdf_msg, file=str(path))

    bot_text = (reply_msg.message if reply_msg else "") or ""
    bot_v = _bot_verdict(bot_text)
    if bot_v == "OTHER":
        n_wait = _other_waits.get(pdf_msg.id, 0) + 1
        _other_waits[pdf_msg.id] = n_wait
        print(
            f"AGENT_DEFENDER_WAIT_REPLY msg={pdf_msg.id} bot=OTHER n={n_wait}",
            flush=True,
        )
        if n_wait < _OTHER_WAIT_MAX:
            return
        # Stale / non-verdict reply — stop spinning; do not treat as CLEAN miss.
        print(
            f"AGENT_DEFENDER_SKIP_STALE msg={pdf_msg.id} bot=OTHER after={n_wait}",
            flush=True,
        )
        _other_waits.pop(pdf_msg.id, None)
        seen.add(pdf_msg.id)
        _save_seen(seen)
        return
    _other_waits.pop(pdf_msg.id, None)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    bank, result, _ = route(data)
    loc = str(result.get("verdict") or "")
    codes = _flag_codes(result)
    interesting = bot_v in {"CLEAN", "UNKNOWN"} or loc in {
        "ЧИСТО", "НЕИЗВЕСТНЫЙ ДОКУМЕНТ",
    } or (bot_v == "FAKE" and loc == "ЧИСТО") or (bot_v == "CLEAN" and loc == "ФЕЙК")

    harden_notes: list[str] = []
    caption = (pdf_msg.message or "")
    if loc in {"ЧИСТО", "НЕИЗВЕСТНЫЙ ДОКУМЕНТ"} and bank in {"Т-Банк", "Сбербанк"}:
        harden_notes = _auto_harden(data, bank, path, caption=caption)
        if any(n.startswith("pin_") for n in harden_notes):
            # re-route after pin
            bank, result, _ = route(data)
            loc = str(result.get("verdict") or "")
            codes = _flag_codes(result)
            _deploy_pins()

    payload = {
        "msg_id": pdf_msg.id,
        "file": name,
        "path": str(path),
        "sha16": sha[:16],
        "bot": bot_v,
        "local": loc,
        "bank": bank,
        "flags": codes,
        "caption": (caption[:120]).replace("\n", " | "),
        "bot_text": bot_text[:220].replace("\n", " | "),
        "interesting": interesting,
        "auto_harden": harden_notes,
    }
    line = "AGENT_DEFENDER_CASE " + json.dumps(payload, ensure_ascii=False)
    print(line, flush=True)
    _log_line(line)
    if interesting:
        miss = (
            f"AGENT_DEFENDER_MISS bot={bot_v} local={loc} bank={bank} "
            f"file={name} sha={sha[:16]} path={path} harden={harden_notes}"
        )
        print(miss, flush=True)
        _log_line(miss)
    seen.add(pdf_msg.id)
    _save_seen(seen)


async def poll_once(client, seen: set[int]) -> int:
    bot = await client.get_entity(_BOT)
    msgs = await client.get_messages(bot, limit=40)
    # newest first; outgoing PDF then typically previous index = bot reply
    n = 0
    for i, m in enumerate(msgs):
        if m.id in seen:
            continue
        if not (m.out and m.document and (m.document.mime_type or "").endswith("pdf")):
            continue
        # wait briefly for reply if missing
        reply = msgs[i - 1] if i > 0 and not msgs[i - 1].out else None
        if reply is None:
            # fetch newer messages specifically
            newer = await client.get_messages(bot, min_id=m.id, limit=5)
            for nm in newer:
                if not nm.out and nm.id > m.id:
                    reply = nm
                    break
        if reply is None:
            print(f"AGENT_DEFENDER_WAIT_REPLY msg={m.id}", flush=True)
            continue
        await _handle_pdf(client, m, reply, seen)
        n += 1
    return n


async def main() -> None:
    cfg = _load_env()
    cfg["TG_SESSION"] = str(_DIR / ".tg_defender_session")
    client = make_client(cfg)
    await ensure_login(client, cfg)
    seen = _load_seen()
    print(
        f"AGENT_DEFENDER_START inbox={_INBOX} seen={len(seen)} poll={_POLL_SEC}s",
        flush=True,
    )
    # catch up once
    await poll_once(client, seen)
    print("AGENT_DEFENDER_CATCHUP_DONE", flush=True)
    while True:
        try:
            if not client.is_connected():
                await client.connect()
            n = await poll_once(client, seen)
            if n:
                print(f"AGENT_DEFENDER_POLL handled={n}", flush=True)
        except Exception as exc:
            print(f"AGENT_DEFENDER_ERR {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(5)
            try:
                await client.connect()
            except Exception:
                pass
        await asyncio.sleep(_POLL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
