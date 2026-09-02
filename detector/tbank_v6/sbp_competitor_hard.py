"""Hard competitor-matching SBP assembly fingerprint.

Rule intent:
- detect a malformed FontFile2 glyf payload on embedded TinkoffSans
- treat that physical defect as standalone proof, independent of SBP fields
- exclude the known benign 405-byte variant
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import threading
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont

from ..ff2_pool import extract_fontfile2_stream_blobs
from ..sbp_cipher import extract_sbp_opid
from ..tbank_sbp_content import extract_sbp_opid_geometric

_WARN_RE = re.compile(r"too much glyph data: (\d+) excess bytes")
_TARGET_TUPLE = "1|6|0|G1|004|00117|770901"
_TARGET_TUPLES = frozenset({
    _TARGET_TUPLE,
    "1|0|0|G1|002|00117|791103",
    "0|1|0|G1|005|00117|770901",
    # Genuine slot-018 receipts use these route tuples with well-formed glyf.
    # The competitor's native-looking follow-up kept H/0 but retained physical
    # TTF residue (115 excess bytes), so the tuple is only a gate, never proof.
    "0|H|0|G1|018|00117|791103",
    "1|S|0|G1|018|00117|791103",
})
_BENIGN_WARN_VALUES = frozenset({405})
STANDALONE_GLYF_CODE = "TBANK_FONT_GLYF_TRAILING_DATA"


@dataclass
class CompetitorHardResult:
    flags: list[tuple[str, str]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _tuple_from_opid(opid: str) -> str:
    if not opid or len(opid) != 32:
        return ""
    return "|".join([
        opid[14],      # route_marker
        opid[15],      # control
        opid[16],      # separator
        opid[17:19],   # class
        opid[19:22],   # slot
        opid[22:27],   # bank5
        opid[26:32],   # suffix
    ])


def _sbp_tuple7(pdf_bytes: bytes, text: str, sbp_stats: dict) -> str:
    fields = (sbp_stats.get("sbp_link_fields") or {})
    from_stats = "|".join(
        str(fields.get(k, ""))
        for k in ("route_marker", "control", "separator", "class", "slot", "bank5", "suffix")
    )
    if from_stats.strip("|"):
        return from_stats
    opid = extract_sbp_opid_geometric(pdf_bytes, text) or extract_sbp_opid(text or "") or ""
    return _tuple_from_opid(opid)


def _collect_glyf_warn_values(pdf_bytes: bytes) -> list[int]:
    vals: list[int] = []
    log_messages: list[str] = []
    owner_thread = threading.get_ident()

    class _CurrentThreadHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.thread == owner_thread:
                log_messages.append(record.getMessage())

    glyf_logger = logging.getLogger("fontTools.ttLib.tables._g_l_y_f")
    handler = _CurrentThreadHandler()
    glyf_logger.addHandler(handler)
    for item in extract_fontfile2_stream_blobs(pdf_bytes):
        name = str(item.get("font_name") or "")
        if "TinkoffSans-" not in name:
            continue
        ttf = item.get("bytes")
        if not isinstance(ttf, (bytes, bytearray)):
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                tt = TTFont(io.BytesIO(ttf))
                if "glyf" not in tt:
                    continue
                glyf = tt["glyf"]
                for gname in tt.getGlyphOrder():
                    try:
                        _ = glyf[gname].isComposite()
                    except Exception:
                        continue
            vals.extend(int(v) for v in _WARN_RE.findall(buf.getvalue()))
        finally:
            try:
                tt.close()
            except Exception:
                pass
    glyf_logger.removeHandler(handler)
    vals.extend(int(v) for v in _WARN_RE.findall("\n".join(log_messages)))
    return vals


def _residue_match(tuple7: str, warn_values: list[int]) -> bool:
    """Tuple alone is common on genuines (00117/G1). Need a real glyf overrun.

    Empty warn list used to fire as matched (`not has_only_benign` on []),
    which FAKE'd OpenPDF originals like чеки/т банк/сбп1.pdf.
    """
    if tuple7 not in _TARGET_TUPLES or not warn_values:
        return False
    uniq = set(warn_values)
    return not uniq.issubset(_BENIGN_WARN_VALUES)


def _nonbenign_residue_match(warn_values: list[int]) -> bool:
    """A malformed TinkoffSans glyf payload is proof without an SBP tuple."""
    return bool(warn_values) and not set(warn_values).issubset(_BENIGN_WARN_VALUES)


def check_sbp_competitor_hard(
    pdf_bytes: bytes,
    text: str = "",
    sbp_stats: dict | None = None,
) -> CompetitorHardResult:
    out = CompetitorHardResult()
    tuple7 = _sbp_tuple7(pdf_bytes, text, sbp_stats or {})
    warn_values = _collect_glyf_warn_values(pdf_bytes)
    uniq_values = sorted(set(warn_values))
    matched = _nonbenign_residue_match(warn_values)
    out.stats = {
        "tuple7": tuple7,
        "target_tuple7": _TARGET_TUPLE,
        "target_tuples": sorted(_TARGET_TUPLES),
        "warn_count": len(warn_values),
        "warn_values": uniq_values,
        "benign_warn_values": sorted(_BENIGN_WARN_VALUES),
        "matched": matched,
    }
    if matched:
        out.flags.append((
            STANDALONE_GLYF_CODE,
            (
                "встроенный TinkoffSans содержит физический хвост за границей "
                f"таблицы glyf: warn={uniq_values}; benign-ветка 405 исключена"
            ),
        ))
    return out
