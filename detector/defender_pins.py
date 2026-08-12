# -*- coding: utf-8 -*-
"""Runtime-extensible known-fake font pins (Kron defender auto-harden).

JSON sidecars are appended by tools/tg_defender_watch.py on CLEAN slips.
Static frozensets in rules/fonts remain the committed baseline.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_TBANK_EXTRA = Path(__file__).resolve().parent / "tbank_v6" / "k_font_002_extra.json"
_SBER_EXTRA = Path(__file__).resolve().parent / "sber_v2" / "known_fake_fontfile2_extra.json"
_lock = threading.Lock()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_tbank_extra_packs() -> set[tuple[str, str]]:
    data = _read_json(_TBANK_EXTRA)
    out: set[tuple[str, str]] = set()
    try:
        from .tbank_v6.genuine_f2_packs import GENUINE_F2_PACKS
    except Exception:
        GENUINE_F2_PACKS = frozenset()
    for item in data.get("packs") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            g, l = str(item[0]).lower(), str(item[1]).lower()
            if len(g) == 64 and len(l) == 64 and (g, l) not in GENUINE_F2_PACKS:
                out.add((g, l))
    return out


def load_sber_extra_sha16() -> set[str]:
    data = _read_json(_SBER_EXTRA)
    try:
        from .sber_v2.genuine_ff2_sha16 import GENUINE_SBER_FF2_SHA16
    except Exception:
        GENUINE_SBER_FF2_SHA16 = frozenset()
    out: set[str] = set()
    for h in data.get("sha16") or []:
        s = str(h).strip().lower()
        if len(s) == 16 and all(c in "0123456789abcdef" for c in s):
            if s not in GENUINE_SBER_FF2_SHA16:
                out.add(s)
    return out


def add_tbank_pack(glyf: str, loca: str) -> bool:
    """Append F2 glyf/loca pack. Returns True if newly added.

    Refuses packs seen on genuine T-Bank corpus (K-FONT-002 FP guard).
    """
    glyf, loca = glyf.lower(), loca.lower()
    try:
        from .tbank_v6.genuine_f2_packs import GENUINE_F2_PACKS
        if (glyf, loca) in GENUINE_F2_PACKS:
            return False
    except Exception:
        pass
    with _lock:
        data = _read_json(_TBANK_EXTRA)
        packs = [tuple(x) for x in (data.get("packs") or []) if isinstance(x, (list, tuple)) and len(x) == 2]
        if (glyf, loca) in {(str(a).lower(), str(b).lower()) for a, b in packs}:
            return False
        packs.append((glyf, loca))
        data["packs"] = [[a, b] for a, b in packs]
        _write_json(_TBANK_EXTRA, data)
        return True


def add_sber_sha16(sha16: str) -> bool:
    sha16 = sha16.lower().strip()
    try:
        from .sber_v2.genuine_ff2_sha16 import GENUINE_SBER_FF2_SHA16
        if sha16 in GENUINE_SBER_FF2_SHA16:
            return False
    except Exception:
        pass
    with _lock:
        data = _read_json(_SBER_EXTRA)
        cur = [str(x).lower() for x in (data.get("sha16") or [])]
        if sha16 in cur:
            return False
        cur.append(sha16)
        data["sha16"] = cur
        _write_json(_SBER_EXTRA, data)
        return True
