"""Exact known-fake signatures for sparse9 (OTP clone kits)."""

from __future__ import annotations

# 3200 озон 4610.pdf — OTP iText phone template + foreign bank5=00118 NSPK id.
OTP_KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    "c1cf4afe01d82b8fa6b9e0523cb08efebf89b7906309570619c4a6ccd5c1f7e4",
})

OTP_KNOWN_FAKE_SBP_IDS: frozenset[str] = frozenset({
    "B62211954129430P0B10120011821301",
})

# Shared clone-kit NSPK tail (also seen on VTB transfer_receipt …0011821301).
OTP_KNOWN_FAKE_SBP_TAILS: frozenset[str] = frozenset({
    "0011821301",
})
