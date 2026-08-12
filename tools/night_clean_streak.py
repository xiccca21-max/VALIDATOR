"""Overnight: track consecutive CLEAN SEQ from defender inbox / watch log.

Emits AGENT_NIGHT_STREAK when ≥2 CLEANs in a row (bot or local), so the
agent can crack structural HARD (0-FP reassembly only). Idle-safe: waits.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_INBOX = _ROOT / "output" / "defender_inbox"
_STATE = _ROOT / "output" / "night_clean_streak.json"
_LOG = _ROOT / "output" / "defender_watch.log"
_POLL = 45


def _load() -> dict:
    if not _STATE.exists():
        return {"streak": 0, "last_ids": [], "cracked": []}
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"streak": 0, "last_ids": [], "cracked": []}


def _save(st: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _scan_log_cases(since_pos: int) -> tuple[list[dict], int]:
    if not _LOG.exists():
        return [], since_pos
    data = _LOG.read_bytes()
    if since_pos > len(data):
        since_pos = 0
    chunk = data[since_pos:].decode("utf-8", "replace")
    cases = []
    for line in chunk.splitlines():
        if "AGENT_DEFENDER_CASE " not in line:
            continue
        try:
            payload = json.loads(line.split("AGENT_DEFENDER_CASE ", 1)[1])
        except Exception:
            continue
        cases.append(payload)
    return cases, len(data)


def _is_clean(case: dict) -> bool:
    """Proton miss only — local ЧИСТО with bot=FAKE is defender lag, not a streak."""
    bot = str(case.get("bot") or "")
    return bot == "CLEAN"


def main() -> None:
    st = _load()
    # Fresh start: skip historical backlog — only react to NEW cases.
    if not st.get("log_pos") and _LOG.exists():
        st["log_pos"] = _LOG.stat().st_size
        st["streak"] = 0
        _save(st)
    log_pos = int(st.get("log_pos") or 0)
    print(
        f"AGENT_NIGHT_START streak={st.get('streak')} poll={_POLL}s "
        f"log_pos={log_pos} inbox={_INBOX}",
        flush=True,
    )
    while True:
        cases, log_pos = _scan_log_cases(log_pos)
        st["log_pos"] = log_pos
        for case in cases:
            mid = case.get("msg_id")
            if mid in st.get("last_ids", [])[-20:]:
                continue
            clean = _is_clean(case)
            interesting = bool(case.get("interesting"))
            if clean:
                st["streak"] = int(st.get("streak") or 0) + 1
                st.setdefault("last_ids", []).append(mid)
                st["last_ids"] = st["last_ids"][-40:]
                st["last_clean"] = case
                print(
                    "AGENT_NIGHT_CLEAN "
                    + json.dumps(
                        {
                            "streak": st["streak"],
                            "msg_id": mid,
                            "file": case.get("file"),
                            "path": case.get("path"),
                            "bot": case.get("bot"),
                            "local": case.get("local"),
                            "bank": case.get("bank"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if st["streak"] >= 2:
                    print(
                        "AGENT_NIGHT_STREAK "
                        + json.dumps(
                            {
                                "streak": st["streak"],
                                "prompt": (
                                    "Kron→proton: ≥2 CLEAN SEQ in a row. Crack via "
                                    "structural reassembly HARD only (0 FP on future "
                                    "genuines). No novelty atlases / exact-size "
                                    "whitelists. Files in output/defender_inbox and "
                                    "last_clean in output/night_clean_streak.json. "
                                    "Deploy if 0-FP HARD found. Continue waiting."
                                ),
                                "last_clean": case,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            else:
                if st.get("streak"):
                    print(
                        f"AGENT_NIGHT_STREAK_RESET was={st['streak']} "
                        f"bot={case.get('bot')} local={case.get('local')}",
                        flush=True,
                    )
                st["streak"] = 0
            if interesting and not clean:
                print(
                    f"AGENT_NIGHT_NOTE interesting non-clean "
                    f"bot={case.get('bot')} local={case.get('local')} "
                    f"file={case.get('file')}",
                    flush=True,
                )
            _save(st)
        if not cases:
            print("AGENT_NIGHT_IDLE waiting for Kron->proton PDFs", flush=True)
        time.sleep(_POLL)


if __name__ == "__main__":
    main()
