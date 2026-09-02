"""K-TBANK-ID-REUSE-001 — trailer /ID reuse with differing content."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .reputation import extract_opid, file_hash
from .sbp_cipher import extract_receipt_datetime, extract_sbp_opid
from .structure import content_stream_bytes
from .tbank_jasper_profile import PROFILE_ID, claims_confirmed_tbank_profile
from .tbank_receipt_format import _extract_receipt_number

RULE_ID = "K-TBANK-ID-REUSE-001"
HARD_CODE = "TBANK_TRAILER_ID_REUSED"
CANONICAL_MISMATCH_CODE = "TBANK_TRAILER_ID_CANONICAL_CONTENT_MISMATCH"

_DB_PATH = Path(__file__).with_name("tbank_id_reuse.db")
_ID_PAIR_RE = re.compile(
    rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]"
    rb"|/ID\s*\[\s*\(([^)]+)\)\s*\(([^)]+)\)\s*\]",
)
_STORE_LIMIT = 2000
_CANONICAL_PATH = Path(__file__).with_name("tbank_trailer_canonical.json")
_CANONICAL_FALLBACK: dict[tuple[str, str], str] = {
    (
        "bd9984ed1d7404c034bd0908bf4ebe83",
        "0a5198225dd4bbe2104dba77fb303617",
    ): "738cc81237f5fe271d1612568f348381a81b9a58f6e275cb1f2a51d3fb1e2eff",
}


def _load_canonical_id_content() -> dict[tuple[str, str], str]:
    """Load confirmed /ID→content bindings; unknown future IDs stay allowed."""
    try:
        raw = json.loads(_CANONICAL_PATH.read_text(encoding="utf-8"))
        out: dict[tuple[str, str], str] = {}
        for key, content_sha in raw.items():
            id0, id1 = str(key).split(":", 1)
            if (
                len(id0) == 32
                and len(id1) == 32
                and len(str(content_sha)) == 64
            ):
                out[(id0.lower(), id1.lower())] = str(content_sha).lower()
        return out or dict(_CANONICAL_FALLBACK)
    except Exception:
        return dict(_CANONICAL_FALLBACK)


# A trailer pair is the PDF document identity. Competitor files copy pairs
# from confirmed originals while replacing /Contents. Bind known identities
# to canonical content; never reject an unknown pair merely for being new.
_CANONICAL_ID_CONTENT_SHA256 = _load_canonical_id_content()
_CANONICAL_ID0_CONTENT_SHA256: dict[str, str] = {}
for (_canonical_id0, _canonical_id1), _canonical_sha in (
    _CANONICAL_ID_CONTENT_SHA256.items()
):
    _previous_sha = _CANONICAL_ID0_CONTENT_SHA256.get(_canonical_id0)
    if _previous_sha is None or _previous_sha == _canonical_sha:
        _CANONICAL_ID0_CONTENT_SHA256[_canonical_id0] = _canonical_sha


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    profile: str = PROFILE_ID


@dataclass
class IdReuseResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trailer_id (
            id0          TEXT,
            id1          TEXT,
            file_sha     TEXT,
            content_sha  TEXT,
            receipt_no   TEXT,
            op_datetime  TEXT,
            opid         TEXT,
            profile      TEXT,
            seen_at      REAL,
            PRIMARY KEY (id0, id1, file_sha)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_trailer_pair ON trailer_id(id0, id1)")
    return con


def extract_trailer_id_pair(pdf_bytes: bytes) -> tuple[str, str]:
    sx = pdf_bytes.rfind(b"startxref")
    zone = pdf_bytes[:sx] if sx >= 0 else pdf_bytes
    refs = list(_ID_PAIR_RE.finditer(zone))
    if not refs:
        return "", ""
    m = refs[-1]
    if m.group(1):
        return m.group(1).decode("ascii").lower(), m.group(2).decode("ascii").lower()
    return m.group(3).decode("latin1"), m.group(4).decode("latin1")


def check_trailer_id_reuse(
    pdf_bytes: bytes,
    text: str,
    *,
    producer: str = "",
    creator: str = "",
    file_hash_value: str = "",
) -> IdReuseResult:
    out = IdReuseResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out

    id0, id1 = extract_trailer_id_pair(pdf_bytes)
    if not id0 or not id1:
        out.stats["skipped"] = "trailer_id_missing"
        return out

    fh = file_hash_value or file_hash(pdf_bytes)
    content = content_stream_bytes(pdf_bytes) or b""
    content_sha = hashlib.sha256(content).hexdigest()
    receipt_no = _extract_receipt_number(text, content)
    dt = extract_receipt_datetime(text, prefer_first_line=True)
    op_dt = dt.isoformat(sep=" ") if dt else ""
    opid = extract_sbp_opid(text) or extract_opid(text) or ""

    out.stats.update({
        "id0": id0[:16],
        "id1": id1[:16],
        "file_sha": fh[:16],
        "content_sha": content_sha[:16],
        "receipt_no": receipt_no,
        "opid": opid[:16] if opid else "",
    })

    canonical_content_sha = _CANONICAL_ID_CONTENT_SHA256.get((id0, id1))
    canonical_scope = "pair"
    if canonical_content_sha is None:
        # PDF /ID[0] is the permanent document identifier; /ID[1] may be
        # rewritten on modification. Changing only ID[1] must not sever the
        # original identity-to-content binding.
        canonical_content_sha = _CANONICAL_ID0_CONTENT_SHA256.get(id0)
        canonical_scope = "permanent_id0"
    if canonical_content_sha and content_sha != canonical_content_sha:
        out.flags.append(HardFlag(
            code=CANONICAL_MISMATCH_CODE,
            detail=(
                f"trailer /ID[0]=<{id0[:8]}…> ({canonical_scope}) принадлежит "
                "каноническому оригиналу, но SHA-256 decoded /Contents "
                f"{content_sha[:16]}… вместо {canonical_content_sha[:16]}…"
            ),
            rule_id="K-TBANK-ID-CANONICAL-001",
        ))
        out.stats["canonical_content_sha"] = canonical_content_sha[:16]
        out.stats["canonical_content_match"] = False
        out.stats["canonical_scope"] = canonical_scope

    con = _con()
    try:
        rows = con.execute(
            "SELECT file_sha, content_sha, receipt_no, op_datetime, opid FROM trailer_id "
            "WHERE id0=? AND id1=? AND file_sha!=?",
            (id0, id1, fh),
        ).fetchall()
        for row in rows:
            prev_fh, prev_cs, prev_rn, prev_dt, prev_op = row
            if prev_fh == fh:
                continue
            diffs: list[str] = []
            if prev_cs != content_sha:
                diffs.append("content stream")
            if prev_rn and receipt_no and prev_rn != receipt_no:
                diffs.append(f"номер {prev_rn}→{receipt_no}")
            if prev_dt and op_dt and prev_dt != op_dt:
                diffs.append(f"дата {prev_dt}→{op_dt}")
            if prev_op and opid and prev_op != opid:
                diffs.append(f"ID {prev_op[:12]}…→{opid[:12]}…")
            if diffs:
                out.flags.append(HardFlag(
                    code=HARD_CODE,
                    detail=(
                        f"trailer /ID[<{id0[:8]}…><{id1[:8]}…>] уже встречался "
                        f"с другим содержимым: {', '.join(diffs)}"
                    ),
                ))
                break

        con.execute(
            "INSERT OR REPLACE INTO trailer_id "
            "(id0,id1,file_sha,content_sha,receipt_no,op_datetime,opid,profile,seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (id0, id1, fh, content_sha, receipt_no, op_dt, opid, PROFILE_ID, time.time()),
        )
        n = con.execute("SELECT COUNT(*) FROM trailer_id").fetchone()[0]
        if n > _STORE_LIMIT:
            con.execute(
                "DELETE FROM trailer_id WHERE rowid IN ("
                "SELECT rowid FROM trailer_id ORDER BY seen_at ASC LIMIT ?)",
                (n - _STORE_LIMIT,),
            )
        con.commit()
    finally:
        con.close()

    return out
