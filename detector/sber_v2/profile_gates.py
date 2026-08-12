"""Profile gate helpers for Sber v2 rules."""

from __future__ import annotations

from .atlas import atlas_profile
from .rules import PROFILE_IDS
from .sbp_exact_profile import (
    is_exact_sbp_outgoing_jasper,
    is_sbp_jasper_near_miss,
)

__all__ = [
    "exact_profile_match",
    "known_atlas_profile",
    "is_new_coherent_profile",
    "profile_allows_rule",
    "profile_skeleton_known",
    "is_exact_sbp_outgoing_jasper",
    "is_sbp_jasper_near_miss",
]


def exact_profile_match(profile_id: str) -> bool:
    return bool(profile_id) and profile_id in PROFILE_IDS


def known_atlas_profile(profile_id: str) -> bool:
    return bool(atlas_profile(profile_id))


def is_new_coherent_profile(profile_id: str, generator_path: str) -> bool:
    if profile_id in PROFILE_IDS and known_atlas_profile(profile_id):
        return False
    if generator_path == "unknown_coherent":
        return True
    return profile_id in ("", "unknown", "unknown_coherent")


def profile_allows_rule(profile_id: str, *, require_exact: bool = True) -> bool:
    """HARD field/geometry rules require an exact known profile."""
    if require_exact:
        return exact_profile_match(profile_id) and known_atlas_profile(profile_id)
    return bool(profile_id)


def profile_skeleton_known(profile_id: str, skeleton: str | None) -> bool:
    if not skeleton:
        return False
    known = set((atlas_profile(profile_id).get("content_skeletons") or []))
    return skeleton in known
