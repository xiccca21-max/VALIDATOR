"""Exact externally confirmed known-fake signatures for Sber v2."""

from __future__ import annotations

# Content-AST / shell hashes confirmed as malicious with zero original collisions.
KNOWN_GENERATOR_SKELETONS: frozenset[str] = frozenset()
KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    # sber_17.08_ORIGINAL.pdf — confirmed fake; its structural layers are
    # indistinguishable from the Jasper/iText bank profile.
    "816a3428d742fb0ef2b59afbaef99c36442b8986023c1dbd3cee2cb0f0110d03",
})
