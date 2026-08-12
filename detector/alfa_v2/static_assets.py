"""Decoded stable-image and Quartz ICC validation for Alfa receipts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .pdfutil import objects, stream_role
from .streams import identify_emitter
from .types import ForensicResult

ATLAS_DIR = Path(__file__).with_name("atlas_data")
CORPUS_SCAN = Path(__file__).parents[1] / "atlas_data" / "_alfa_corpus_scan.json"
RULE_GROUP = "alfa_v2.static_assets"
# Oracle BI genuines always embed the seal/stamp image 603×258 (n=16).
# Rebuilds may keep logo assets (900×105, 90×138) and drop the stamp.
_ORACLE_STAMP_ROLE = "603x258"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _load_atlas() -> dict[str, Any]:
    configured = _read_json(ATLAS_DIR / "static_assets.json")
    if isinstance(configured, dict):
        return configured
    # The corpus scan is a defensive bootstrap source for the three decoded,
    # dimension-addressed stable images. No sample file path is ever trusted.
    rows = _read_json(CORPUS_SCAN)
    atlas: dict[str, Any] = {}
    if not isinstance(rows, list):
        return atlas
    for emitter in ("oracle", "quartz"):
        samples = [row for row in rows if isinstance(row, dict) and row.get("gen") == emitter]
        role_values: dict[str, set[str]] = {}
        for sample in samples:
            for image in sample.get("images", []):
                if not isinstance(image, dict):
                    continue
                key = f"{image.get('w')}x{image.get('h')}"
                if image.get("sha"):
                    role_values.setdefault(key, set()).add(str(image["sha"]))
        stable = {key: sorted(values) for key, values in role_values.items() if len(values) == 1}
        if stable:
            atlas[emitter] = {"images": stable}
    return atlas


def _integer(dictionary: bytes, key: bytes) -> int | None:
    match = re.search(rb"/" + re.escape(key) + rb"\s+(\d+)", dictionary)
    return int(match.group(1)) if match else None


def check_static_assets(
    pdf: bytes,
    *,
    producer: str = "",
    document_rebuild_proven: bool = False,
) -> ForensicResult:
    result = ForensicResult()
    emitter = identify_emitter(pdf, producer)
    atlas = _load_atlas()
    expected = atlas.get(emitter, {}) if isinstance(atlas.get(emitter), dict) else {}
    image_atlas = expected.get("images", {})
    if not isinstance(image_atlas, dict) or not image_atlas:
        result.stats["skipped"] = "asset_atlas_unavailable"
        return result

    seen: dict[str, dict[str, Any]] = {}
    icc_seen: list[dict[str, Any]] = []
    for obj in objects(pdf).values():
        role = stream_role(obj)
        if role == "image" and obj.decoded_stream is not None:
            width, height = _integer(obj.dictionary, b"Width"), _integer(obj.dictionary, b"Height")
            asset_role = f"{width}x{height}"
            if asset_role in image_atlas:
                digest = hashlib.sha256(obj.decoded_stream).hexdigest()
                allowed = image_atlas[asset_role]
                allowed_set = {allowed} if isinstance(allowed, str) else set(allowed or [])
                seen[asset_role] = {
                    "object": obj.number,
                    "sha256": digest,
                    "match": digest in allowed_set,
                }
        elif role == "icc" and obj.decoded_stream is not None:
            digest = hashlib.sha256(obj.decoded_stream).hexdigest()
            allowed_icc = expected.get("icc", [])
            allowed_set = {allowed_icc} if isinstance(allowed_icc, str) else set(allowed_icc or [])
            icc_seen.append({"object": obj.number, "sha256": digest, "match": digest in allowed_set})

    states = [seen.get(role, {"match": False, "missing": True}) for role in image_atlas]
    if emitter == "quartz" and expected.get("icc"):
        states.extend(icc_seen or [{"match": False, "missing": True, "role": "icc"}])
    matches = sum(bool(state.get("match")) for state in states)
    replacements = len(states) - matches
    partial = matches > 0 and replacements > 0
    result.stats.update(
        emitter=emitter,
        expected_asset_count=len(states),
        matched_asset_count=matches,
        partial_replacement=partial,
        document_rebuild_proven=document_rebuild_proven,
        image_roles=seen,
        icc=icc_seen,
    )
    # Missing stamp while staff logos remain = shell without seal (HARD).
    # Does not require document_rebuild_proven: absence of 603x258 is itself
    # structural (0 FP on чеки/альфа Oracle n=16). Example: Документ (11).pdf.
    if (
        emitter == "oracle"
        and _ORACLE_STAMP_ROLE in image_atlas
    ):
        stamp = seen.get(_ORACLE_STAMP_ROLE)
        stamp_missing = stamp is None or bool(stamp.get("missing"))
        other_staff_matched = sum(
            1
            for role, state in seen.items()
            if role != _ORACLE_STAMP_ROLE and state.get("match")
        )
        result.stats["stamp_role"] = _ORACLE_STAMP_ROLE
        result.stats["stamp_missing"] = stamp_missing
        result.stats["other_staff_matched"] = other_staff_matched
        if stamp_missing and other_staff_matched >= 1:
            result.add(
                "ALFA_STATIC_ASSET_STAMP_MISSING",
                (
                    f"нет штатной печати/штампа Oracle {_ORACLE_STAMP_ROLE}, "
                    f"при этом на месте {other_staff_matched} staff-asset(s) "
                    f"(логотипы) — квитанция без печати банка"
                ),
                group=RULE_GROUP,
                evidence={
                    "images": seen,
                    "stamp_role": _ORACLE_STAMP_ROLE,
                    "other_staff_matched": other_staff_matched,
                },
            )

    if partial and document_rebuild_proven:
        result.add(
            "ALFA_STATIC_ASSET_PARTIAL_REPLACEMENT",
            "Only part of the stable decoded Alfa asset set survived an independently proven rebuild",
            group=RULE_GROUP,
            evidence={"images": seen, "icc": icc_seen, "emitter": emitter},
        )
    elif partial:
        result.add(
            "ALFA_STATIC_ASSET_DRIFT",
            "Partial stable-asset replacement observed without independent document-rebuild proof",
            tier="DIAGNOSTIC",
            group=RULE_GROUP,
        )
    return result


check_assets = check_static_assets
