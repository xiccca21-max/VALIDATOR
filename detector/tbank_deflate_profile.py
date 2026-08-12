"""K-TBANK-DEFLATE-PROFILE-001 — non-canonical Flate/DEFLATE serializer profile."""

from __future__ import annotations

from dataclasses import dataclass, field

from .tbank_flate_profile import FlateStreamProfile, StreamRole, enumerate_flate_streams
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_stream_serializer import check_mixed_flate_serializer

RULE_ID = "K-TBANK-DEFLATE-PROFILE-001"
HARD_CODE = "TBANK_DEFLATE_PROFILE_MISMATCH"


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    object_number: int = 0
    pdf_offset: int = 0
    expected: str = ""
    actual: str = ""
    profile: str = PROFILE_ID


@dataclass
class DeflateProfileResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    profiles: list[FlateStreamProfile] = field(default_factory=list)


def _flag_from_profile(p: FlateStreamProfile, *, reason: str) -> HardFlag:
    return HardFlag(
        code=HARD_CODE,
        detail=(
            f"obj {p.object_number} 0 ({p.role.value}): {reason}; "
            f"offset={p.pdf_offset}; compressed_len={p.compressed_length}; "
            f"canonical_len={p.canonical_length}; "
            f"actual_sha={p.compressed_sha256[:16]}; "
            f"expected_sha={p.canonical_sha256[:16]}; "
            f"first_diff={p.first_diff_offset}"
        ),
        object_number=p.object_number,
        pdf_offset=p.pdf_offset,
        expected=p.canonical_sha256[:16] if p.canonical_sha256 else "",
        actual=p.compressed_sha256[:16],
    )


def check_deflate_profile(
    pdf_bytes: bytes,
    *,
    text: str = "",
    producer: str = "",
    creator: str = "",
) -> DeflateProfileResult:
    out = DeflateProfileResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    profiles = enumerate_flate_streams(pdf_bytes)
    out.profiles = profiles
    out.stats["stream_count"] = len(profiles)

    sr = check_mixed_flate_serializer(
        pdf_bytes,
        text=text,
        producer=producer,
        creator=creator,
        shadow=False,
        profiles=profiles,
    )
    out.stats["serializer"] = sr.stats
    for code, detail in sr.hard_flags:
        out.flags.append(HardFlag(
            code=HARD_CODE,
            detail=detail,
            profile=PROFILE_ID,
        ))

    mismatched = [p for p in profiles if p.decoded and not p.canonical_match]
    canonical = [p for p in profiles if p.decoded and p.canonical_match]
    out.stats["canonical"] = len(canonical)
    out.stats["mismatched"] = len(mismatched)

    if not sr.hard_flags and mismatched:
        page_bad = [p for p in mismatched if p.role == StreamRole.PAGE_CONTENT]
        if page_bad and len(canonical) >= 9:
            for p in page_bad:
                if not any(f.object_number == p.object_number for f in out.flags):
                    out.flags.append(_flag_from_profile(
                        p,
                        reason="selective non-Java DEFLATE on page content stream",
                    ))

    return out
