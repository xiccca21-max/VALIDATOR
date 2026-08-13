"""Deterministic, non-visual PDF mutations used by the generator agent.

The agent may choose and combine mutations, but it never receives a primitive
that can render a branded receipt or insert personal/payment data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


MUTATION_CODES: dict[str, frozenset[str]] = {
    "xref_object_mismatch": frozenset({"XREF_ENTRY_OBJECT_MISMATCH"}),
    "xref_generation_mismatch": frozenset({"XREF_GENERATION_MISMATCH"}),
    "xref_duplicate_live_mapping": frozenset({"XREF_DUPLICATE_LIVE_MAPPING"}),
    "xref_size_conflict": frozenset({"XREF_SIZE_CONTRADICTION"}),
    "stream_length_overrun": frozenset({"STREAM_ENDSTREAM_CONTRADICTION"}),
    "stream_length_type_invalid": frozenset({"STREAM_LENGTH_TYPE_INVALID"}),
    "duplicate_contents": frozenset({"DUPLICATE_CRITICAL_DICT_KEY_CONFLICT"}),
    "page_count_conflict": frozenset({"PAGETREE_COUNT_CONTRADICTION"}),
    "page_parent_conflict": frozenset({"PAGETREE_PARENT_CONTRADICTION"}),
    "missing_contents_reference": frozenset({"PAGE_CONTENT_REFERENCE_INVALID"}),
    "contents_generation_mismatch": frozenset(
        {"INDIRECT_REFERENCE_GENERATION_MISMATCH"}
    ),
}
ALLOWED_MUTATIONS = frozenset(MUTATION_CODES)


@dataclass(frozen=True)
class MutationPlan:
    mutations: tuple[str, ...]
    label: str = ""

    def __post_init__(self) -> None:
        if not self.mutations:
            raise ValueError("a plan needs at least one mutation")
        unknown = set(self.mutations) - ALLOWED_MUTATIONS
        if unknown:
            raise ValueError(f"unsupported mutations: {sorted(unknown)}")
        if len(self.mutations) != len(set(self.mutations)):
            raise ValueError("duplicate mutations are not allowed")

    @property
    def expected_codes(self) -> frozenset[str]:
        return frozenset(
            code
            for mutation in self.mutations
            for code in MUTATION_CODES[mutation]
        )

    @property
    def signature(self) -> str:
        return "+".join(sorted(self.mutations))


def _objects(plan: MutationPlan | None = None) -> dict[int, bytes]:
    mutations = set(plan.mutations if plan else ())
    pages_count = b"9" if "page_count_conflict" in mutations else b"1"
    if "missing_contents_reference" in mutations:
        contents_ref = b"99 0 R"
    elif "contents_generation_mismatch" in mutations:
        contents_ref = b"4 1 R"
    else:
        contents_ref = b"4 0 R"
    contents_entry = b"/Contents " + contents_ref
    if "duplicate_contents" in mutations:
        contents_entry += b" /Contents 2 0 R"

    stream = b"BT /F1 12 Tf 10 10 Td (Synthetic) Tj ET\n"
    if "stream_length_type_invalid" in mutations:
        declared_length = b"/Invalid"
    elif "stream_length_overrun" in mutations:
        declared_length = str(len(stream) + 47).encode()
    else:
        declared_length = str(len(stream)).encode()
    parent = b"1 0 R" if "page_parent_conflict" in mutations else b"2 0 R"
    return {
        1: b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        2: (
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count "
            + pages_count
            + b" >>endobj\n"
        ),
        3: (
            b"3 0 obj<< /Type /Page /Parent "
            + parent
            + b" "
            b"/MediaBox [0 0 200 200] "
            + contents_entry
            + b" >>endobj\n"
        ),
        4: (
            b"4 0 obj<< /Length "
            + declared_length
            + b" >>stream\n"
            + stream
            + b"endstream\nendobj\n"
        ),
    }


def build_pdf(plan: MutationPlan | None = None) -> bytes:
    """Build a tiny structurally valid PDF, then apply selected contradictions."""
    objects = _objects(plan)
    body = bytearray(b"%PDF-1.4\n")
    offsets = {0: 0}
    for number in sorted(objects):
        offsets[number] = len(body)
        body += objects[number]

    xref_pos = len(body)
    entries: list[bytes] = [b"0000000000 65535 f \n"]
    mutations = set(plan.mutations if plan else ())
    for number in sorted(objects):
        offset = offsets[number]
        generation = 0
        if number == 3 and "xref_object_mismatch" in mutations:
            offset = offsets[4]
        if number == 1 and "xref_generation_mismatch" in mutations:
            generation = 1
        entries.append(f"{offset:010d} {generation:05d} n \n".encode())

    body += b"xref\n0 5\n" + b"".join(entries)
    if "xref_duplicate_live_mapping" in mutations:
        body += b"2 1\n" + f"{offsets[3]:010d} 00000 n \n".encode()
    trailer_size = b"3" if "xref_size_conflict" in mutations else b"5"
    body += (
        b"trailer<< /Size "
        + trailer_size
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(body)


def write_candidate(
    directory: Path, round_number: int, index: int, plan: MutationPlan
) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    pdf_bytes = build_pdf(plan)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    stem = f"r{round_number:04d}_{index:03d}_{digest[:12]}"
    pdf_path = directory / f"{stem}.pdf"
    manifest_path = directory / f"{stem}.json"
    manifest: dict[str, object] = {
        "schema": 1,
        "file": pdf_path.name,
        "sha256": digest,
        "synthetic": True,
        "visual_content": False,
        "mutations": list(plan.mutations),
        "expected_codes": sorted(plan.expected_codes),
        "signature": plan.signature,
        "label": plan.label,
    }
    pdf_path.write_bytes(pdf_bytes)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
