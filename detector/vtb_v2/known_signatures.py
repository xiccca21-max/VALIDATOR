"""Exact known-fake signatures for VTB v2."""

from __future__ import annotations

# Linked tuple: (sb_class, bank5, marker, control, slot, suffix)
VTB_KNOWN_FAKE_LINKED_TUPLES: frozenset[tuple[str, str, str, str, str, str]] = frozenset({
    ("G1", "00117", "7", "W", "016", "770901"),
})

VTB_KNOWN_FAKE_SBP_TAILS: frozenset[str] = frozenset({
    "7W0G10160011770901",
})

VTB_KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    "9ddc4942d9248cc6037734a2aadb0ff1d12419581189759ef291f5cc9da57286",
    "0f6562768c2c26d2bb3c568819cd7fdbe2e22083c3ff677d15f84b2cd3bf4db9",
    # transfer_receipt_A62221321431340D0B10070011821301.pdf (CLEAN-miss → WIDTHS runs)
    "b1367b0ddc96b685fb556c40a649c01084ec2ca51ce81d4ec4a23836a6adcd04",
})

VTB_KNOWN_FAKE_SBP_IDS: frozenset[str] = frozenset({
    "B61711110212917W0G10160011770901",
})

VTB_KNOWN_FAKE_SEMANTIC_SHA256: frozenset[str] = frozenset({
    "513ce239dc8f384778f13891429094ae3db7dea9a19ccaf4756604afa21ebb09",
    "7fd6db1214127969dd41b9dd5349f1225cc3876a59e902be058bbbb26159901d",
})

VTB_KNOWN_FAKE_ASSEMBLY_SHA256: frozenset[str] = frozenset({
    "951350a0c80d00d7fbc5256e5c1c0de7d391c463f7e667f89a94c9be1bc376b7",
    "be7f59dfca957fe8d2ee02a717941e7283428668e3e46841e11fbf1ece8f461c",
})
