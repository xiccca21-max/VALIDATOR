"""Observe new Alfa SBP bank5/suffix profiles without blocking CLEAN.

Unknown bank5/suffix pairs absent from the corpus are NOT decisive.
Pipeline HARD checks still enforce timestamp, class, arithmetic, Quartz
structure, fonts/glyphs, metadata linkage and edit absence. When those
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

from .sbp import extract_sbp_id, load_generated_atlas, _route_segments
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


def _flag(bank5: str, suffix: str) -> AlfaFlag:
    return AlfaFlag(
        code=CODE,
        detail=f"bank5={bank5} suffix={suffix}",
        tier="DIAGNOSTIC",
        group="new_sbp_profile",
        rule_id=RULE_ID,
    )


def _known_bank5_suffix() -> set[tuple[str, str]]:
    atlas = load_generated_atlas()
    known: set[tuple[str, str]] = set()
    for key in atlas.linked_route_markers:
        # linked key: (control, class, slot, bank5, suffix)
        if len(key) == 5:
            known.add((key[3], key[4]))
    # Also derive from cores×tails when suffix layout overlaps bank5 tail digit.
    for core in atlas.cores:
        for tail in atlas.tails:
            # Historical corpus used core[22:27] + tail[27:32]; reconstructed
            # suffix is core[-1] + tail when lengths match the live layout.
            if len(core) == 5 and len(tail) == 5:
                known.add((core, core[-1] + tail))
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


def _persist_observation(bank5: str, suffix: str, *, file_hash: str = "") -> bool:
    """Append bank5/suffix if not yet stored. Returns True when newly saved."""
    with _LOCK:
        data = _load_observations()
        profiles = data.setdefault("profiles", [])
        if not isinstance(profiles, list):
            profiles = []
            data["profiles"] = profiles
        for item in profiles:
            if (
                isinstance(item, dict)
                and item.get("bank5") == bank5
                and item.get("suffix") == suffix
            ):
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
            "bank5": bank5,
            "suffix": suffix,
            "first_seen_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "last_seen_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "sightings": 1,
            "example_file_hash": file_hash or "",
            "note": "corpus through 2026-06-29 had bank5∈{00116,00117} only",
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
    """Record unknown bank5/suffix; never escalate to MANUAL/HARD alone."""
    del pdf_bytes, producer, creation_date  # kept for stages call-site compat
    out = CheckResult()
    opid = extract_sbp_id(text) or ""
    if len(opid) != 32:
        out.stats["new_sbp_profile"] = False
        return out

    segs = _route_segments(opid)
    bank5 = segs.get("bank5", "")
    suffix = segs.get("suffix", "")
    out.stats.update({
        "sbp_bank5": bank5,
        "sbp_suffix": suffix,
        "sbp_id": opid,
    })

    if not bank5 or not suffix:
        out.stats["new_sbp_profile"] = False
        return out

    known = _known_bank5_suffix()
    is_new = (bank5, suffix) not in known
    out.stats["known_bank5_suffix"] = not is_new
    out.stats["new_sbp_profile"] = is_new
    if not is_new:
        return out

    saved = _persist_observation(bank5, suffix, file_hash=file_hash)
    out.stats["observation_persisted"] = saved
    out.flags.append(_flag(bank5, suffix))
    return out


# Back-compat alias for older imports / stages during rollout.
check_unconfirmed_quartz_profile = check_new_sbp_profile
