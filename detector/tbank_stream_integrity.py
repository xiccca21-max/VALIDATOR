"""K-TBANK-STREAM-INTEGRITY-001 — stream boundaries and zlib framing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tbank_flate_profile import FlateStreamProfile, enumerate_flate_streams
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile

RULE_ID = "K-TBANK-STREAM-INTEGRITY-001"
HARD_CODE = "TBANK_STREAM_INTEGRITY_VIOLATION"
_STREAM_LEN_RE = re.compile(rb"/Length\s+(\d+)")


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
class StreamIntegrityResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_stream_integrity(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
    profiles: list[FlateStreamProfile] | None = None,
) -> StreamIntegrityResult:
    out = StreamIntegrityResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    profiles = profiles if profiles is not None else enumerate_flate_streams(pdf_bytes)
    out.stats["stream_count"] = len(profiles)

    for p in profiles:
        if p.declared_length is not None and abs(p.declared_length - p.compressed_length) > 2:
            out.flags.append(HardFlag(
                code=HARD_CODE,
                detail=(
                    f"obj {p.object_number} 0: /Length={p.declared_length} "
                    f"≠ фактических {p.compressed_length} байт"
                ),
                object_number=p.object_number,
                pdf_offset=p.pdf_offset,
                expected=str(p.declared_length),
                actual=str(p.compressed_length),
            ))

        if p.decoded and (not p.eof_clean or p.unused_tail or p.unconsumed_tail):
            out.flags.append(HardFlag(
                code=HARD_CODE,
                detail=(
                    f"obj {p.object_number} 0: данные после конца DEFLATE "
                    f"(unused={p.unused_tail}b, tail={len(p.unconsumed_tail)}b, "
                    f"eof_clean={p.eof_clean})"
                ),
                object_number=p.object_number,
                pdf_offset=p.pdf_offset,
            ))

        if p.raw_compressed and p.raw_compressed[:1] != b"\x78":
            out.flags.append(HardFlag(
                code=HARD_CODE,
                detail=f"obj {p.object_number} 0: нестандартный zlib header {p.raw_compressed[:2]!r}",
                object_number=p.object_number,
                pdf_offset=p.pdf_offset,
            ))

    return out
