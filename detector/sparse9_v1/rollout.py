"""Sparse9 v1 rollout: shadow mode + per-bank feature flags."""

from __future__ import annotations

import hashlib
import logging
import os

from ..sparse9_profiles import BANK_KEYS

log = logging.getLogger(__name__)

# Production: sparse9_v1 decides the user verdict (was shadow→bank_spec).
# Corpus gate 2026-08-11: 0 FP_V1 on otp/raif/psb/yandex/wbbank/sovkom/
# rocket/uralsib/bchpb genuines. Per-bank env still overrides.
_DEFAULT_MODE = "full"
_BANK_ENV = {
    "wbbank": "SPARSE9_WBBANK_V1_ROLLOUT",
    "otp": "SPARSE9_OTP_V1_ROLLOUT",
    "psb": "SPARSE9_PSB_V1_ROLLOUT",
    "bchpb": "SPARSE9_BCHPB_V1_ROLLOUT",
    "raif": "SPARSE9_RAIF_V1_ROLLOUT",
    "rocket": "SPARSE9_ROCKET_V1_ROLLOUT",
    "sovkom": "SPARSE9_SOVCOM_V1_ROLLOUT",
    "uralsib": "SPARSE9_URALSIB_V1_ROLLOUT",
    "yandex": "SPARSE9_YANDEX_V1_ROLLOUT",
}


def master_rollout_mode() -> str:
    return (os.environ.get("SPARSE9_V1_ROLLOUT") or _DEFAULT_MODE).strip().lower()


def bank_rollout_mode(bank_key: str) -> str:
    env = _BANK_ENV.get(bank_key, "")
    if env:
        val = (os.environ.get(env) or "").strip().lower()
        if val:
            return val
    return master_rollout_mode()


def _in_rollout_bucket(file_hash: str, percent: int) -> bool:
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    return int(hashlib.sha256(file_hash.encode()).hexdigest(), 16) % 100 < percent


def apply_rollout(v1_result: dict, pdf_bytes: bytes, file_hash: str, bank_key: str) -> dict:
    mode = bank_rollout_mode(bank_key)
    details = dict(v1_result.get("details") or {})
    details["sparse9_v1_shadow"] = {
        "mode": mode,
        "bank_key": bank_key,
        "v1_verdict": v1_result.get("verdict"),
        "v1_flags": (v1_result.get("flags") or [])[:8],
        "v1_expert_report": details.get("expert_report"),
    }

    if mode == "shadow":
        from ..sparse9_legacy import analyze as analyze_legacy
        legacy = analyze_legacy(pdf_bytes, bank_key, file_hash)
        details["sparse9_v1_shadow"]["legacy_verdict"] = legacy.get("verdict")
        details["sparse9_v1_shadow"]["match"] = legacy.get("verdict") == v1_result.get("verdict")
        legacy_details = dict(legacy.get("details") or {})
        legacy_details["sparse9_v1_shadow"] = details["sparse9_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    if mode.isdigit() and not _in_rollout_bucket(file_hash, int(mode)):
        from ..sparse9_legacy import analyze as analyze_legacy
        legacy = analyze_legacy(pdf_bytes, bank_key, file_hash)
        legacy_details = dict(legacy.get("details") or {})
        legacy_details["sparse9_v1_shadow"] = details["sparse9_v1_shadow"]
        legacy["details"] = legacy_details
        return legacy

    v1_result["details"] = details
    return v1_result


def is_sparse9_bank(bank_key: str) -> bool:
    return bank_key in BANK_KEYS
