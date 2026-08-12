"""A-RAIF-CONTENT-CID-ZERO-001 — Identity-H Tj/TJ must not paint CID 0.

Native Raiffeisen iText pdfHTML SBP receipts never emit ``<0000>Tj`` /
CID 0 in content streams. Generators that splice fields sometimes insert a
``.notdef`` (CID 0) between phone and «Банк получателя» → immediate ФЕЙК.

No shadow mode. GID/CID 0 here is a *content* show operand, not FontFile2
.notdef integrity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .structure import content_stream_bytes, find_streams, is_content_stream
from .tbank_reassembly_family_v3 import _cids_from_operand

RULE_ID = "A-RAIF-CONTENT-CID-ZERO-001"
CODE = "RAIF_CONTENT_CID_ZERO"

_SHOW_RE = re.compile(
    rb"("
    rb"\((?:\\.|[^\\()])*\)"
    rb"|<(?:[0-9A-Fa-f]+)>"
    rb"|\[(?:[^\[\]]|\[[^\]]*\])*\]"
    rb")\s*(Tj|TJ|'|\")",
    re.S,
)
_STR_IN_ARRAY_RE = re.compile(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f]+>")


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    tier: str = "A"


@dataclass
class Cid0Result:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _content_blobs(pdf: bytes) -> list[bytes]:
    primary = content_stream_bytes(pdf)
    if primary:
        return [primary]
    out: list[bytes] = []
    for _raw, dec in find_streams(pdf):
        if dec and (is_content_stream(dec) or (b"BT" in dec and b"Tj" in dec)):
            out.append(dec)
    return out


def find_cid0_show_operands(pdf: bytes) -> list[dict[str, Any]]:
    """Return every text-show operand that includes Identity-H CID 0."""
    hits: list[dict[str, Any]] = []
    for content in _content_blobs(pdf):
        for m in _SHOW_RE.finditer(content):
            operand, op = m.group(1), m.group(2).decode("ascii", "replace")
            cids: list[int] = []
            if operand.startswith(b"["):
                for tok in _STR_IN_ARRAY_RE.finditer(operand):
                    cids.extend(_cids_from_operand(tok.group(0)))
            else:
                cids = _cids_from_operand(operand)
            if 0 not in cids:
                continue
            hits.append({
                "operator": op,
                "cid0_count": cids.count(0),
                "cids_sample": cids[:24],
                "operand_preview": operand[:48].decode("latin1", "replace"),
            })
    return hits


def profile_gate_raif_cid0(
    *,
    bank_key: str = "",
    producer: str = "",
    text: str = "",
    channel: str = "",
) -> bool:
    if (bank_key or "").lower() not in ("raif", "raiffeisen"):
        return False
    low = (text or "").lower()
    pr = (producer or "").lower()
    looks_raif_sbp = (
        "квитанция о переводе" in low
        or "систему быстрых платежей" in low
        or "online.raiffeisen.ru" in low
        or "райффайзенбанк" in low
    )
    if not looks_raif_sbp:
        return False
    if channel and channel.lower() not in ("sbp", "channel_sbp"):
        return False
    # Native current form is iText pdfHTML; still run if producer empty.
    if pr and "pdfhtml" not in pr and "itext" not in pr:
        return False
    return True


def check_raif_content_cid0(
    pdf_bytes: bytes,
    *,
    bank_key: str = "raif",
    producer: str = "",
    text: str = "",
    channel: str = "sbp",
) -> Cid0Result:
    out = Cid0Result()
    if not profile_gate_raif_cid0(
        bank_key=bank_key, producer=producer, text=text, channel=channel,
    ):
        out.stats["skipped"] = "profile_gate"
        return out

    hits = find_cid0_show_operands(pdf_bytes)
    out.stats["cid0_show_hits"] = len(hits)
    out.stats["cid0_hits"] = hits[:8]
    if not hits:
        return out

    preview = hits[0].get("operand_preview", "")
    out.flags.append(HardFlag(
        code=CODE,
        detail=(
            f"в content stream нарисован CID 0 (.notdef) через {hits[0].get('operator')}: "
            f"{preview!r} (hits={len(hits)}) — у нативных Raif pdfHTML SBP отсутствует"
        ),
        rule_id=RULE_ID,
    ))
    return out
