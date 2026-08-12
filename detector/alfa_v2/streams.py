"""Role-aware Flate serializer provenance for Oracle and Quartz Alfa PDFs."""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from detector.java_deflater import java_deflate

from .pdfutil import PdfObject, objects, stream_role
from .types import ForensicResult

ATLAS_DIR = Path(__file__).with_name("atlas_data")
RULE_GROUP = "alfa_v2.streams"
_PROTECTED_ROLES = frozenset({"content", "font", "tounicode", "image", "icc", "xref"})
_ORACLE_STANDARD_ROLES = frozenset({"image", "content", "font", "tounicode"})
_EXACT_ORACLE_PRODUCER = "oracle bi publisher 12.2.1.4.0"


@dataclass(frozen=True)
class StreamObservation:
    object_number: int
    role: str
    emitter: str
    canonical_emitter: str | None
    canonical_match: bool
    profile_match: bool
    dynamic: bool


def _load_profiles() -> dict[str, Any]:
    path = ATLAS_DIR / "flate_profiles.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def identify_emitter(pdf: bytes, producer: str = "") -> str:
    probe = (producer.encode("latin1", "ignore") + b" " + pdf[:16384]).lower()
    if b"oracle bi publisher" in probe:
        return "oracle"
    if b"quartz pdfcontext" in probe or b"ios version" in probe:
        return "quartz"
    return "unknown"


def _level_candidates(emitter: str, role: str, atlas: dict[str, Any]) -> tuple[int, ...]:
    raw = atlas.get(emitter, {}).get(role, {}).get("levels")
    if not isinstance(raw, list):
        raw = atlas.get(emitter, {}).get("levels")
    levels = tuple(int(x) for x in raw or () if isinstance(x, int) and -1 <= x <= 9)
    # Defaults are canonical byte generators, not length/ratio heuristics.
    return levels or ((6,) if emitter == "oracle" else (6, 9) if emitter == "quartz" else ())


def _deflate_profile(raw: bytes) -> tuple[int, int, int]:
    if len(raw) < 3:
        return (0, 0, -1)
    return raw[0], raw[1], (raw[2] >> 1) & 0x03


def _reproducible_levels(decoded: bytes, raw: bytes) -> tuple[int, ...]:
    """Return zlib levels 1-9 whose full compressed bytes equal ``raw``."""
    return tuple(
        level
        for level in range(1, 10)
        if zlib.compress(decoded, level) == raw
    )


def _canonical_for(
    decoded: bytes, emitter: str, role: str, atlas: dict[str, Any]
) -> list[bytes]:
    return [zlib.compress(decoded, level) for level in _level_candidates(emitter, role, atlas)]


def _observe(obj: PdfObject, claimed: str, atlas: dict[str, Any]) -> StreamObservation | None:
    if obj.raw_stream is None or obj.decoded_stream is None or b"/FlateDecode" not in obj.dictionary:
        return None
    role = stream_role(obj)
    if role not in _PROTECTED_ROLES:
        return None
    canonical_emitter: str | None = None
    exact = False
    profile = False
    actual_profile = _deflate_profile(obj.raw_stream)
    hit_levels = _reproducible_levels(obj.decoded_stream, obj.raw_stream)
    for emitter in ("oracle", "quartz"):
        generated = _canonical_for(obj.decoded_stream, emitter, role, atlas)
        if obj.raw_stream in generated:
            canonical_emitter, exact, profile = emitter, True, True
            break
        if any(_deflate_profile(candidate) == actual_profile for candidate in generated):
            if emitter == claimed:
                profile = True
    return StreamObservation(
        object_number=obj.number,
        role=role,
        emitter=claimed,
        canonical_emitter=canonical_emitter,
        canonical_match=exact and canonical_emitter == claimed,
        profile_match=profile,
        dynamic=actual_profile[2] == 2 or not hit_levels,
    )



def _oracle_near_canonical(raw: bytes, decoded: bytes) -> dict[str, Any]:
    """Oracle BI content streams are near zlib.compress(..., 6), not byte-identical.

    Genuine corpus content: first differing byte at offset >= 3 and small length delta.
    Foreign re-serializers often diverge earlier and/or with large size drift.
    """
    canonical = zlib.compress(decoded, 6)
    first = next(
        (i for i, (a, b) in enumerate(zip(raw, canonical)) if a != b),
        min(len(raw), len(canonical)),
    )
    len_delta = abs(len(raw) - len(canonical))
    return {
        "first_diff": first,
        "len_delta": len_delta,
        "near": first >= 3 and len_delta <= 40,
        "canonical_len": len(canonical),
        "raw_len": len(raw),
    }


def _corpus_compressed_sets() -> dict[str, set[str]]:
    """Role -> compressed SHA-256 values observed on the Alfa corpus."""
    path = ATLAS_DIR / "streams-images.v1.json"
    out: dict[str, set[str]] = {"image": set(), "font": set(), "tounicode": set(), "content": set()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return out
    for row in data.get("static_images_by_file") or []:
        if not isinstance(row, dict):
            continue
        for image in row.get("images") or []:
            if isinstance(image, dict) and image.get("compressed_sha256_provenance_only"):
                out["image"].add(str(image["compressed_sha256_provenance_only"]))
    # Fonts / ToUnicode / content compressed hashes live in streams_by_file roles.
    for row in data.get("streams_by_file") or []:
        if not isinstance(row, dict):
            continue
        for stream in row.get("streams") or []:
            if not isinstance(stream, dict):
                continue
            digest = stream.get("compressed_sha256_provenance_only")
            roles = stream.get("roles") or []
            if not digest:
                continue
            role_names = {str(r) for r in roles}
            if "static_image" in role_names or "image" in role_names:
                out["image"].add(str(digest))
            if any("fontfile2" in r for r in role_names):
                out["font"].add(str(digest))
            if any("tounicode" in r for r in role_names):
                out["tounicode"].add(str(digest))
            if any(r in {"page_content", "content"} for r in role_names):
                out["content"].add(str(digest))
    # Fallback: scan not required; font hashes also in font-inventory.
    try:
        fonts = json.loads((ATLAS_DIR / "font-inventory.v1.json").read_text(encoding="utf-8"))
        for row in fonts.get("files") or []:
            for font in row.get("fonts") or []:
                # inventory stores decoded FontFile2 sha, not compressed — skip
                pass
    except (OSError, ValueError, TypeError):
        pass
    return out


def _pdf_version(pdf: bytes) -> str:
    match = re.match(rb"%PDF-(\d\.\d)", pdf or b"")
    return match.group(1).decode("ascii") if match else ""


def _object_count(pdf: bytes) -> int:
    return len(re.findall(rb"(?m)^\s*\d+\s+\d+\s+obj\b", pdf or b""))


def _exact_oracle_bi_profile(pdf: bytes, producer: str, role_counts: dict[str, int]) -> bool:
    """Gate for Java Deflater(6) full-reserialization HARD.

    Requires the claimed exact Oracle BI Publisher 12.2.1.4.0 shell: PDF 1.6,
    confirmed 16-object Oracle graph, and the standard six-stream role set.
    Unknown / non-standard templates must not become HARD.
    """
    if (producer or "").strip().lower() != _EXACT_ORACLE_PRODUCER:
        return False
    if _pdf_version(pdf) != "1.6":
        return False
    if _object_count(pdf) != 16:
        return False
    return (
        role_counts.get("image") == 3
        and role_counts.get("content") == 1
        and role_counts.get("font") == 1
        and role_counts.get("tounicode") == 1
        and sum(role_counts.get(r, 0) for r in _ORACLE_STANDARD_ROLES) == 6
    )


def _java_deflate_stream_rows(pdf: bytes) -> list[dict[str, Any]]:
    """Compare each protected Flate stream to Java ``Deflater(6, false)``."""
    rows: list[dict[str, Any]] = []
    for obj in objects(pdf).values():
        if obj.raw_stream is None or obj.decoded_stream is None:
            continue
        if b"/FlateDecode" not in obj.dictionary:
            continue
        role = stream_role(obj)
        if role not in _ORACLE_STANDARD_ROLES:
            continue
        canonical = java_deflate(obj.decoded_stream, level=6)
        is_canonical = canonical is not None and canonical == obj.raw_stream
        rows.append(
            {
                "object": obj.number,
                "role": role,
                "is_canonical": is_canonical,
                "java_available": canonical is not None,
                "raw_len": len(obj.raw_stream),
                "canonical_len": None if canonical is None else len(canonical),
                "compressed_sha256": hashlib.sha256(obj.raw_stream).hexdigest(),
            }
        )
    return rows


def check_streams(pdf: bytes, *, producer: str = "") -> ForensicResult:
    """Hard-flag cross-emitter mixes and canonical Oracle assets + foreign streams."""
    result = ForensicResult()
    claimed = identify_emitter(pdf, producer)
    if claimed == "unknown":
        result.stats["skipped"] = "emitter_unknown"
        return result
    atlas = _load_profiles()
    observations = [
        obs
        for obj in objects(pdf).values()
        if (obs := _observe(obj, claimed, atlas)) is not None
    ]
    # Attach full recompression evidence for Oracle exact-profile decisions.
    level_hits: dict[int, tuple[int, ...]] = {}
    for obj in objects(pdf).values():
        if obj.raw_stream is None or obj.decoded_stream is None:
            continue
        if b"/FlateDecode" not in obj.dictionary:
            continue
        if stream_role(obj) not in _PROTECTED_ROLES:
            continue
        level_hits[obj.number] = _reproducible_levels(obj.decoded_stream, obj.raw_stream)

    role_counts = {
        role: sum(o.role == role for o in observations)
        for role in sorted({o.role for o in observations})
    }
    result.stats.update(
        emitter=claimed,
        stream_count=len(observations),
        roles=role_counts,
        zlib_level_hits={str(k): list(v) for k, v in level_hits.items()},
    )
    cross = [o for o in observations if o.canonical_emitter and o.canonical_emitter != claimed]
    matching = [o for o in observations if o.canonical_match]
    noncanonical = [o for o in observations if not o.canonical_match]
    unreproducible = [
        o for o in noncanonical
        if not level_hits.get(o.object_number)
    ]
    mismatching_dynamic = [
        o for o in observations
        if not o.canonical_match and o.dynamic and o.profile_match
    ]
    # Exact Oracle BI 12.2.1.4.0: Java Deflater(6) byte identity on all six streams.
    oracle_exact = _exact_oracle_bi_profile(pdf, producer, role_counts)
    result.stats["exact_oracle_bi_12214"] = oracle_exact
    java_rows: list[dict[str, Any]] = []
    java_canonical = 0
    java_foreign = 0
    java_available = False
    if oracle_exact and claimed == "oracle":
        java_rows = _java_deflate_stream_rows(pdf)
        java_available = bool(java_rows) and all(r.get("java_available") for r in java_rows)
        java_canonical = sum(1 for r in java_rows if r.get("is_canonical"))
        java_foreign = sum(1 for r in java_rows if r.get("java_available") and not r.get("is_canonical"))
        result.stats.update(
            java_deflate_level=6,
            java_available=java_available,
            java_canonical_streams=java_canonical,
            java_foreign_streams=java_foreign,
            java_stream_rows=java_rows,
        )
        if java_available and len(java_rows) == 6 and java_canonical == 6:
            # Canonical Oracle BI profile — no serializer provenance flags.
            return result
        if java_available and len(java_rows) == 6 and java_canonical == 0 and java_foreign == 6:
            result.add(
                "ALFA_ORACLE_FULL_DEFLATE_PROVENANCE_MISMATCH",
                "exact Oracle BI Publisher 12.2.1.4.0 profile claims six Flate streams, "
                "but 0/6 match Java Deflater(6,false) canonical bytes (full foreign reserialization)",
                group=RULE_GROUP,
                evidence={
                    "producer": producer,
                    "pdf_version": _pdf_version(pdf),
                    "object_count": _object_count(pdf),
                    "roles": role_counts,
                    "canonical": java_canonical,
                    "foreign": java_foreign,
                    "streams": java_rows,
                },
            )
            return result
        if java_available and len(java_rows) == 6 and 0 < java_canonical < 6:
            result.add(
                "ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE",
                f"Flate streams mix Java Deflater(6) canonical ({java_canonical}/6) "
                f"with foreign recompression ({java_foreign}/6)",
                group=RULE_GROUP,
                evidence={
                    "producer": producer,
                    "canonical": java_canonical,
                    "foreign": java_foreign,
                    "streams": java_rows,
                },
            )
            return result

    # Fallback mixed detection: corpus-canonical static assets + foreign content
    # (used when Java is unavailable or profile is not the exact 12.2.1.4.0 gate).
    corpus_raw = _corpus_compressed_sets() if claimed == "oracle" else {}
    asset_canonical: list[dict[str, Any]] = []
    content_foreign: list[dict[str, Any]] = []
    if claimed == "oracle":
        parsed_objects = objects(pdf)
        for obj in parsed_objects.values():
            if obj.raw_stream is None or obj.decoded_stream is None:
                continue
            if b"/FlateDecode" not in obj.dictionary:
                continue
            role = stream_role(obj)
            digest = hashlib.sha256(obj.raw_stream).hexdigest()
            if role in {"image", "font", "tounicode"}:
                known = corpus_raw.get(role) or set()
                if digest in known:
                    asset_canonical.append(
                        {"object": obj.number, "role": role, "compressed_sha256": digest}
                    )
            elif role == "content":
                near = _oracle_near_canonical(obj.raw_stream, obj.decoded_stream)
                levels = level_hits.get(obj.number, ())
                if not near["near"] and not levels:
                    content_foreign.append(
                        {
                            "object": obj.number,
                            "compressed_sha256": digest,
                            **near,
                            "zlib_levels": list(levels),
                        }
                    )
    mixed_zlib = bool(
        "oracle bi publisher 12.2.1.4.0" in (producer or "").lower()
        and asset_canonical
        and any(item["role"] == "image" for item in asset_canonical)
        and content_foreign
    )
    selective = bool(matching and (mismatching_dynamic or unreproducible))
    if cross or selective or mixed_zlib:
        evidence = {
            "claimed_emitter": claimed,
            "producer": producer,
            "cross_emitter_objects": [o.object_number for o in cross],
            "canonical_objects": [o.object_number for o in matching],
            "corpus_canonical_assets": asset_canonical,
            "foreign_content_streams": content_foreign,
            "unreproducible_objects": [o.object_number for o in unreproducible],
            "selectively_recompressed_objects": [o.object_number for o in mismatching_dynamic],
            "role_states": [
                {
                    "object": o.object_number,
                    "role": o.role,
                    "canonical_emitter": o.canonical_emitter,
                    "canonical_match": o.canonical_match,
                    "dynamic": o.dynamic,
                    "zlib_levels": list(level_hits.get(o.object_number, ())),
                }
                for o in observations
            ],
        }
        code = (
            "ALFA_MIXED_ZLIB_SERIALIZER_PROVENANCE"
            if mixed_zlib
            else "ALFA_MIXED_SERIALIZER_PROVENANCE"
        )
        result.add(
            code,
            "Flate streams mix canonical Oracle bytes with foreign/dynamic recompression",
            group=RULE_GROUP,
            evidence=evidence,
        )
    elif observations and not matching:
        result.add(
            "ALFA_NEW_FLATE_PROFILE",
            "All role-matched Flate streams use one unrecognized coherent serializer profile",
            tier="DIAGNOSTIC",
            group=RULE_GROUP,
        )
    return result


check_flate_streams = check_streams
