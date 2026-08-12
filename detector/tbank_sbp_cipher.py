"""Мягкая проверка шифра СБП-ID в чеках Т-Банка — обёртка над detector/sbp_cipher.py."""

from __future__ import annotations

from .sbp_cipher import CipherFlag, CipherResult, validate_nspk_sbp_cipher

# re-export для обратной совместимости
validate_tbank_sbp_cipher = validate_nspk_sbp_cipher
extract_receipt_datetime = __import__(
    "detector.sbp_cipher", fromlist=["extract_receipt_datetime"]
).extract_receipt_datetime


def first_forgery_flag(result: CipherResult) -> tuple[bool, str]:
    if not result.flags:
        return (False, "")
    f = result.flags[0]
    return (True, f"[{f.code}] {f.detail}")
