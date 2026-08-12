"""K-TBANK-ID-REUSE-001 — trailer /ID reuse with differing content."""

from __future__ import annotations

import hashlib
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

_DB_PATH = Path(__file__).with_name("tbank_id_reuse.db")
_ID_PAIR_RE = re.compile(
    rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]"
    rb"|/ID\s*\[\s*\(([^)]+)\)\s*\(([^)]+)\)\s*\]",
)
_STORE_LIMIT = 2000


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
