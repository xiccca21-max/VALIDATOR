"""Stream integrity checks for Sber v2."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

from ..structure import validate_active_content, validate_stream_compression
from .types import SberFlag

_STREAM_OBJ_RE = re.compile(
    rb"(\d+)\s+(\d+)\s+obj(.*?)stream(\r\n|\n|\r)(.*?)endstream",
    re.S,
)
_LENGTH_RE = re.compile(rb"/Length\s+(\d+)(?:\s+0\s+R)?")
_FILTER_FLATE = re.compile(rb"/Filter\s*(?:\[\s*)?/FlateDecode")


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "stream") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_stream_integrity(pdf_bytes: bytes) -> CheckResult:
    """Length ↔ boundary, zlib eof/unused/trailing."""
    out = CheckResult()
    try:
        mismatches = 0
        zlib_bad = 0
        checked = 0
        for m in _STREAM_OBJ_RE.finditer(pdf_bytes):
            hdr = m.group(3)
            raw = m.group(5)
            # Strip trailing whitespace that PDF writers sometimes leave before endstream
            body = raw.rstrip(b"\r\n")
            lm = _LENGTH_RE.search(hdr)
            if not lm:
                continue
            # Skip indirect length refs (group is object number, not length)
            if re.search(rb"/Length\s+\d+\s+0\s+R", hdr):
                continue
            declared = int(lm.group(1))
            checked += 1
            if abs(declared - len(body)) > 2:
                mismatches += 1
                out.flags.append(_f(
                    "SBER_STREAM_INTEGRITY_VIOLATION",
                    f"obj {m.group(1).decode()} 0: /Length={declared} ≠ {len(body)} байт",
                ))
                out.flags.append(_f(
                    "STREAM_LENGTH_MISMATCH",
                    f"obj {m.group(1).decode()} 0 length mismatch",
                ))
                continue
            if not _FILTER_FLATE.search(hdr):
                continue
            if not body:
                continue
            try:
                dec = zlib.decompress(body)
                # Check unused data after zlib stream
                dobj = zlib.decompressobj()
                _ = dobj.decompress(body)
                unused = dobj.unused_data or b""
                if unused and len(unused) > 2:
                    zlib_bad += 1
                    out.flags.append(_f(
                        "SBER_STREAM_INTEGRITY_VIOLATION",
                        f"obj {m.group(1).decode()} 0: zlib unused tail {len(unused)}b",
                    ))
                _ = dec  # decoded successfully
            except Exception as exc:
                zlib_bad += 1
                out.flags.append(_f(
                    "SBER_STREAM_INTEGRITY_VIOLATION",
                    f"obj {m.group(1).decode()} 0: zlib fail ({exc})",
                ))
                out.flags.append(_f(
                    "STREAM_DECOMPRESSION_FAILED",
                    f"obj {m.group(1).decode()} 0 decompress failed",
                ))

        out.stats.update({
            "streams_checked": checked,
            "length_mismatches": mismatches,
            "zlib_issues": zlib_bad,
        })

        # Soft anomalies → Tier-B / diagnostic via compression helper
        soft = validate_stream_compression(pdf_bytes)
        out.stats["compression"] = soft.stats
        for code, det in zip(soft.codes, soft.details):
            # Mixed zlib / large decoded streams are normal for Jasper+JPEG Sber.
            if code in (
                "STREAM_COMPRESSION_RATIO_OUTLIER",
                "DECODED_STREAM_SIZE_OUTLIER",
                "STREAM_FILTER_ANOMALY",
            ):
                out.flags.append(_f(code, det, tier="DIAGNOSTIC"))
            elif code == "UNEXPECTED_STREAM_FILTER":
                # DCTDecode/JPX are legitimate image filters on Sber internals.
                if "DCTDecode" in det or "JPXDecode" in det:
                    out.flags.append(_f(code, det, tier="DIAGNOSTIC"))
                else:
                    out.flags.append(_f(code, det, tier="HARD"))

        act = validate_active_content(pdf_bytes)
        for code, det in zip(act.codes, act.details):
            out.flags.append(_f(code, det, tier="HARD", group="active"))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
