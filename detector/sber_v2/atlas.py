"""Load sber_atlas_v2.json (built from the 22 originals)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ATLAS_PATH = Path(__file__).with_name("atlas_data") / "sber_atlas_v2.json"


@lru_cache(maxsize=1)
def load_atlas() -> dict[str, Any]:
    if not ATLAS_PATH.is_file():
        return {}
    try:
        return json.loads(ATLAS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def atlas_profile(profile_id: str) -> dict[str, Any]:
    return (load_atlas().get("profiles") or {}).get(profile_id) or {}


def known_sbp_markers() -> set[str]:
    emp = load_atlas().get("sbp_empirical") or {}
    return set(emp.get("markers") or [])


def known_sbp_tail_prefixes() -> set[str]:
    emp = load_atlas().get("sbp_empirical") or {}
    return set(emp.get("tail_prefix4") or [])
