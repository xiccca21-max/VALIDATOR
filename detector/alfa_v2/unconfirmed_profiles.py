"""Observe new Alfa SBP core/tail profiles without blocking CLEAN.

Unknown core/tail pairs absent from the corpus are NOT decisive.
Pipeline HARD checks still enforce timestamp, structure, Quartz
fonts/glyphs, metadata linkage and edit absence. When those
pass, the document stays CLEAN and the new pair is recorded as
ALFA_NEW_SBP_PROFILE_OBSERVED.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sbp import canonical_segments, extract_sbp_id, load_generated_atlas
from .types import AlfaFlag

RULE_ID = "K-ALFA-NEW-SBP-PROFILE-001"
CODE = "ALFA_NEW_SBP_PROFILE_OBSERVED"

_HERE = Path(__file__).resolve().parent
_OBS_PATH = _HERE / "atlas_data" / "alfa_new_sbp_profile_observations.json"
_LOCK = threading.Lock()


@dataclass
class CheckResult:
    flags: list[AlfaFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    manual_review: bool = False  # never True — new profiles are observational


def _flag(core: str, tail: str) -> AlfaFlag:
    return AlfaFlag(
        code=CODE,
        detail=f"core={core} tail={tail}",
        tier="DIAGNOSTIC",
        group="new_sbp_profile",
        rule_id=RULE_ID,
    )


def _pair_from_item(item: dict[str, Any]) -> tuple[str, str] | None:
    core = str(item.get("core") or item.get("bank5") or "")
    tail = str(item.get("tail") or "")
    suffix = str(item.get("suffix") or "")
    if not tail and len(suffix) == 5:
        tail = suffix
    elif not tail and len(suffix) == 6 and core and suffix.startswith(core[-1:]):
        # Legacy overlapping suffix [26:32] = core[-1] + tail.
        tail = suffix[1:]
    if len(core) == 5 and len(tail) == 5:
        return core, tail
    return None


def _known_core_tail() -> set[tuple[str, str]]:
    atlas = load_generated_atlas()
    known: set[tuple[str, str]] = set(atlas.core_tails)
    for core in atlas.cores:
        for tail in atlas.tails:
            if len(core) == 5 and len(tail) == 5:
                known.add((core, tail))
    return known


def _load_observations() -> dict[str, Any]:
    try:
        if _OBS_PATH.is_file():
            data = json.loads(_OBS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"schema": "alfa-new-sbp-profile-observations", "version": "1", "profiles": []}


def _persist_observation(core: str, tail: str, *, file_hash: str = "") -> bool:
    """Append core/tail if not yet stored. Returns True when newly saved."""
    with _LOCK:
        data = _load_observations()
        profiles = data.setdefault("profiles", [])
        if not isinstance(profiles, list):
            profiles = []
            data["profiles"] = profiles
        for item in profiles:
            if not isinstance(item, dict):
                continue
            pair = _pair_from_item(item)
            if pair == (core, tail):
                item["core"] = core
                item["tail"] = tail
                item["last_seen_utc"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                item["sightings"] = int(item.get("sightings") or 1) + 1
                if file_hash and not item.get("example_file_hash"):
                    item["example_file_hash"] = file_hash
                try:
                    _OBS_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _OBS_PATH.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                except OSError:
                    return False
                return False

        profiles.append({
            "core": core,
            "tail": tail,
            "first_seen_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "last_seen_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "sightings": 1,
            "example_file_hash": file_hash or "",
            "note": "corpus through 2026-06-29 had core∈{00116,00117} only",
        })
        try:
            _OBS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _OBS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return True
        except OSError:
            return False


def check_new_sbp_profile(
    pdf_bytes: bytes,
    text: str,
    *,
    producer: str = "",
    creation_date: str = "",
    file_hash: str = "",
) -> CheckResult:
    """Record unknown core/tail; never escalate to MANUAL/HARD alone."""
    del pdf_bytes, producer, creation_date  # kept for stages call-site compat
    out = CheckResult()
    opid = extract_sbp_id(text) or ""
    if len(opid) != 32:
        out.stats["new_sbp_profile"] = False
        return out

    segs = canonical_segments(opid)
    core = segs.get("core", "")
    tail = segs.get("tail", "")
    out.stats.update({
        "sbp_core": core,
        "sbp_tail": tail,
        "sbp_channel": segs.get("channel", ""),
        "sbp_id": opid,
    })

    if not core or not tail:
        out.stats["new_sbp_profile"] = False
        return out

    known = _known_core_tail()
    is_new = (core, tail) not in known
    out.stats["known_core_tail"] = not is_new
    out.stats["new_sbp_profile"] = is_new
    if not is_new:
        return out

    saved = _persist_observation(core, tail, file_hash=file_hash)
    out.stats["observation_persisted"] = saved
    out.flags.append(_flag(core, tail))
    return out


# Back-compat alias for older imports / stages during rollout.
check_unconfirmed_quartz_profile = check_new_sbp_profile
