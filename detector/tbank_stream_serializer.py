"""K-TBANK-STREAM-SERIALIZER-001 — mixed Flate serializer provenance detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tbank_flate_profile import FlateStreamProfile, StreamRole, enumerate_flate_streams

RULE_ID = "K-TBANK-STREAM-SERIALIZER-001"
HARD_CODE = "MIXED_FLATE_SERIALIZER_PROVENANCE"
REASON = "MIXED_FLATE_SERIALIZER_PROVENANCE"

_JASPER_CREATOR_RE = re.compile(
    r"JasperReports Library version 6\.20\.3",
    re.I,
)
_OPENPDF_PRODUCER_RE = re.compile(
    r"OpenPDF 1\.3\.30\.jaspersoft\.2",
    re.I,
)

_CRITICAL_MARKERS = (
    b"BT", b"Tj", b"TJ", b"Tm", b"Tf",
)
_CRITICAL_TEXT_PATTERNS = re.compile(
    r"(?i)(сумм|итого|получател|отправител|телефон|карт|статус|"
    r"сбп|квитанц|\d{2}\.\d{2}\.\d{4}|\+7|₽|руб|успешно|перевод)",
)


@dataclass
class SerializerResult:
    hard_flags: list[tuple[str, str]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    profiles: list[FlateStreamProfile] = field(default_factory=list)


def _claims_jasper_openpdf(pdf_bytes: bytes, *, producer: str = "", creator: str = "") -> bool:
    if creator and _JASPER_CREATOR_RE.search(creator):
        if producer and _OPENPDF_PRODUCER_RE.search(producer):
            return True
    blob = pdf_bytes[:12000]
    cr = re.search(rb"/Creator\s*\(([^)]*)\)", blob)
    pr = re.search(rb"/Producer\s*\(([^)]*)\)", blob)
    c = (cr.group(1).decode("latin1", "replace") if cr else creator) or ""
    p = (pr.group(1).decode("latin1", "replace") if pr else producer) or ""
    return bool(_JASPER_CREATOR_RE.search(c) and _OPENPDF_PRODUCER_RE.search(p))


def _has_critical_fields(profile: FlateStreamProfile, visible_text: str = "") -> bool:
    dec = profile.decoded
    if not dec:
        return False
    if not all(m in dec for m in _CRITICAL_MARKERS[:3]):
        return False
    if _CRITICAL_TEXT_PATTERNS.search(dec.decode("latin1", "replace")):
        return True
    if visible_text and _CRITICAL_TEXT_PATTERNS.search(visible_text):
        return True
    return bool(re.search(rb"\d{5,}", dec) or b"F1" in dec or b"F2" in dec)


def _uniform_new_profile(profiles: list[FlateStreamProfile]) -> bool:
    """All streams share the same non-canonical but uniform serializer fingerprint."""
    if not profiles:
        return False
    fps = {p.huffman_fingerprint for p in profiles if p.huffman_fingerprint}
    if len(fps) == 1 and not profiles[0].canonical_match:
        return True
    mism = [p for p in profiles if not p.canonical_match]
    if len(mism) == len(profiles):
        return True
    return False


def _format_evidence(
    bad: FlateStreamProfile,
    canonical_count: int,
    total_canonical_eligible: int,
    mismatch_count: int,
    original_collisions: int,
    unique_originals: int,
) -> str:
    abs_off = bad.pdf_offset + bad.first_diff_offset if bad.first_diff_offset >= 0 else bad.pdf_offset
    lines = [
        f"[{RULE_ID}]",
        "Выборочное пересжатие критического content stream",
        "",
        f"PDF object: {bad.object_number} 0",
        f"Role: Page /Contents",
        f"Compressed offset: {bad.pdf_offset}",
        f"Actual compressed length: {bad.compressed_length}",
        f"Canonical compressed length: {bad.canonical_length}",
        f"Actual compressed SHA-256: {bad.compressed_sha256}",
        f"Canonical compressed SHA-256: {bad.canonical_sha256}",
        f"First differing relative offset: {bad.first_diff_offset}",
        f"First differing absolute PDF offset: {abs_off}",
        f"Other canonical streams: {canonical_count}/{total_canonical_eligible}",
        f"Mismatching critical streams: {mismatch_count}",
        f"Original collisions: {original_collisions}/{unique_originals} unique SHA",
        f"Second implementation confirmation: {'PASS' if bad.second_analyzer_pass else 'FAIL'}",
        "",
        "Почему это не нормальная вариативность:",
        "внутри одного PDF девять независимых ресурсов соответствуют",
        "заявленному Jasper/OpenPDF serializer-профилю, но поток с видимыми",
        "реквизитами был сериализован отдельно.",
        "",
        "Влияние:",
        "подтверждённое постгенерационное вмешательство → ФЕЙК.",
    ]
    return "\n".join(lines)


def _role_state(
    profiles: list[FlateStreamProfile],
    resource_role: str,
) -> list[FlateStreamProfile]:
    return [p for p in profiles if p.resource_role == resource_role]


def _check_text_font_serializer_split(
    profiles: list[FlateStreamProfile],
    visible_text: str,
) -> tuple[bool, dict, str]:
    """
    Jasper/OpenPDF shell split: images + F3 retain canonical Java DEFLATE,
    while page content and all F1/F2 text/font streams were recompressed.
    """
    page = [p for p in profiles if p.role == StreamRole.PAGE_CONTENT]
    images = [p for p in profiles if p.role == StreamRole.IMAGE]
    f3_font = _role_state(profiles, "F3 FontFile2")
    critical = {
        "page content": page,
        "F1 FontFile2": _role_state(profiles, "F1 FontFile2"),
        "F1 ToUnicode": _role_state(profiles, "F1 ToUnicode"),
        "F2 FontFile2": _role_state(profiles, "F2 FontFile2"),
        "F2 ToUnicode": _role_state(profiles, "F2 ToUnicode"),
    }

    all_selected = images + f3_font
    for streams in critical.values():
        all_selected.extend(streams)
    canonical_available = bool(all_selected) and all(
        p.decoded and p.canonical_length > 0 for p in all_selected
    )
    shell_canonical = (
        len(images) == 4
        and bool(f3_font)
        and all(p.canonical_match for p in images + f3_font)
    )
    critical_present = all(bool(streams) for streams in critical.values())
    critical_noncanonical = critical_present and all(
        not p.canonical_match
        for streams in critical.values()
        for p in streams
    )
    page_has_fields = any(_has_critical_fields(p, visible_text) for p in page)

    stats = {
        "image_objects": [p.object_number for p in images],
        "image_count": len(images),
        "f3_font_objects": [p.object_number for p in f3_font],
        "critical_objects": {
            role: [p.object_number for p in streams]
            for role, streams in critical.items()
        },
        "canonical_available": canonical_available,
        "shell_canonical": shell_canonical,
        "critical_present": critical_present,
        "critical_noncanonical": critical_noncanonical,
        "page_has_critical_fields": page_has_fields,
    }
    hit = (
        canonical_available
        and shell_canonical
        and critical_noncanonical
        and page_has_fields
    )
    detail = (
        f"[{RULE_ID}] Jasper/OpenPDF shell имеет canonical Java Deflater bytes "
        f"для F3 FontFile2 и четырёх image streams "
        f"(objects={[p.object_number for p in images + f3_font]}), но page content, "
        "F1 FontFile2, F1 ToUnicode, F2 FontFile2 и F2 ToUnicode одновременно "
        "не совпадают с decoded→CanonicalDeflater output "
        f"(objects={stats['critical_objects']}); текстовые и шрифтовые потоки "
        "пересобраны другим сериализатором"
    )
    return hit, stats, detail


def check_mixed_flate_serializer(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
    original_collisions: int = 0,
    unique_originals: int = 119,
    shadow: bool = False,
    profiles: list[FlateStreamProfile] | None = None,
) -> SerializerResult:
    """
    K-TBANK-STREAM-SERIALIZER-001 hard rule.
    Detects selective post-generation recompression of page content stream.
    """
    res = SerializerResult()
    profiles = profiles if profiles is not None else enumerate_flate_streams(pdf_bytes)
    res.profiles = profiles
    res.stats["stream_count"] = len(profiles)

    if not profiles:
        res.stats["skipped"] = "no_flate_streams"
        return res

    if not _claims_jasper_openpdf(pdf_bytes, producer=producer, creator=creator):
        res.stats["skipped"] = "metadata_not_jasper_openpdf"
        return res

    canonical = [p for p in profiles if p.canonical_match]
    mismatched = [p for p in profiles if not p.canonical_match]
    res.stats["canonical_streams"] = len(canonical)
    res.stats["mismatched_streams"] = len(mismatched)
    res.stats["mismatch_objects"] = [p.object_number for p in mismatched]

    if not mismatched:
        res.stats["verdict"] = "all_canonical"
        return res

    split_hit, split_stats, split_detail = _check_text_font_serializer_split(
        profiles,
        text,
    )
    res.stats["text_font_serializer_split"] = split_stats
    if split_hit:
        res.evidence.append(split_detail)
        if not shadow:
            res.hard_flags.append((HARD_CODE, split_detail))
        res.stats["verdict"] = "FAKE" if res.hard_flags else "shadow_hit"
        return res

    if _uniform_new_profile(profiles):
        res.stats["verdict"] = "NEW_GENERATOR_PROFILE"
        return res

    noncritical_roles = {StreamRole.FONT, StreamRole.TOUNICODE, StreamRole.IMAGE, StreamRole.OTHER}
    noncritical = [p for p in profiles if p.role in noncritical_roles]
    noncritical_canonical = [p for p in noncritical if p.canonical_match]
    res.stats["noncritical_canonical"] = f"{len(noncritical_canonical)}/{len(noncritical)}"

    if len(noncritical) >= 9 and len(noncritical_canonical) < len(noncritical):
        res.stats["skipped"] = "noncritical_streams_not_all_canonical"
        return res

    mismatch_page = [p for p in mismatched if p.role == StreamRole.PAGE_CONTENT]
    if not mismatch_page:
        res.stats["skipped"] = "mismatch_not_page_content"
        return res

    if any(p.role in noncritical_roles for p in mismatched):
        res.stats["skipped"] = "mismatch_includes_non_page_content"
        return res

    critical_bad = [p for p in mismatch_page if _has_critical_fields(p, text)]
    if not critical_bad:
        res.stats["skipped"] = "no_critical_fields_in_mismatch"
        return res

    eligible = [p for p in profiles if p.role != StreamRole.PAGE_CONTENT or p in canonical]
    canonical_eligible = [p for p in eligible if p.canonical_match]
    if len(canonical_eligible) < 9:
        res.stats["skipped"] = f"insufficient_canonical_peers={len(canonical_eligible)}"
        return res

    for bad in critical_bad:
        if not bad.second_analyzer_pass:
            res.stats["skipped"] = "second_analyzer_not_confirmed"
            return res

    if original_collisions > 0:
        res.stats["skipped"] = f"original_collisions={original_collisions}"
        return res

    for bad in critical_bad:
        ev = _format_evidence(
            bad,
            canonical_count=len(canonical_eligible),
            total_canonical_eligible=len(eligible),
            mismatch_count=len(critical_bad),
            original_collisions=original_collisions,
            unique_originals=unique_originals,
        )
        res.evidence.append(ev)
        if not shadow:
            res.hard_flags.append((
                HARD_CODE,
                ev,
            ))

    res.stats["verdict"] = "FAKE" if res.hard_flags else "shadow_hit"
    return res


def profiles_table(profiles: list[FlateStreamProfile]) -> list[dict]:
    """Tabular summary for deliverables."""
    return [
        {
            "object": f"{p.object_number} 0",
            "role": p.role.value,
            "resource_role": p.resource_role,
            "canonical_match": p.canonical_match,
            "actual_hash": p.compressed_sha256[:16],
            "expected_hash": p.canonical_sha256[:16] if p.canonical_sha256 else "",
            "actual_len": p.compressed_length,
            "expected_len": p.canonical_length,
        }
        for p in profiles
    ]
