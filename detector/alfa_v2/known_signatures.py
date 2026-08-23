"""Exact signatures for user-confirmed Alfa forgeries."""

from __future__ import annotations


KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    # PDF Document (89).pdf — confirmed fake Quartz/iOS shell clone.
    "9b614fe525d1940859bcca746fa92c712dad30dd178c3eb553f8d9c7ada2c9d2",
})

