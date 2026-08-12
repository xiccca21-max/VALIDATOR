"""A-GPB-LATENT-RECEIPT-REVISION-001 — unreachable prior receipt revisions.

HARD_CODE = GPB_LATENT_RECEIPT_REVISION_CONFLICT (score 95).

Detects saved previous versions of a Gazprombank cheque that remain as
unreachable content streams in the PDF object graph.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

RULE_ID = "A-GPB-LATENT-RECEIPT-REVISION-001"
HARD_CODE = "GPB_LATENT_RECEIPT_REVISION_CONFLICT"
CREATION_HARD_CODE = "GPB_OPERATION_AFTER_PDF_CREATION"
SCORE = 95

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj")
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")
_STREAM_RE = re.compile(rb"stream\r?\n", re.I)
_TRAILER_RE = re.compile(rb"trailer\s*<<(.*?)>>", re.S | re.I)
_ROOT_RE = re.compile(rb"/Root\s+(\d+)\s+\d+\s+R")
_INFO_RE = re.compile(rb"/Info\s+(\d+)\s+\d+\s+R")
_PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([+\-Z].*)?"
)

_GPB_ANCHORS = (
    "чек по операции",
    "дата и время операции",
    "тип операции",
    "статус операции",
    "сумма",
    "сумма комиссии",
    "rrn",
    "номер операции сбп",
)

_DYNAMIC_FIELDS = (
    "operation_datetime",
    "operation_type",
    "status",
    "recipient_bank",
    "recipient_phone",
    "recipient_name",
    "currency",
    "fx_amount",
    "amount",
    "commission",
    "total",
)


@dataclass
class Graph003Result:
    hard: bool = False
    flags: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    score: int = 0


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_span(pdf_bytes: bytes, num: int) -> tuple[int, int] | None:
    om = re.search(rf"{num}\s+\d+\s+obj".encode(), pdf_bytes)
    if not om:
        return None
    end = pdf_bytes.find(b"endobj", om.start())
    if end < 0:
        return om.start(), min(len(pdf_bytes), om.start() + 200000)
    return om.start(), end + 6


def _object_body(pdf_bytes: bytes, num: int) -> bytes:
    span = _object_span(pdf_bytes, num)
    if not span:
        return b""
    return pdf_bytes[span[0]:span[1]]


def _all_object_nums(pdf_bytes: bytes) -> set[int]:
    return {int(m.group(1)) for m in _OBJ_RE.finditer(pdf_bytes)}


def _trailer_roots(pdf_bytes: bytes) -> list[int]:
    roots: list[int] = []
    # Prefer last trailer
    for m in _TRAILER_RE.finditer(pdf_bytes):
        chunk = m.group(1)
        rm = _ROOT_RE.search(chunk)
        if rm:
            roots.append(int(rm.group(1)))
        im = _INFO_RE.search(chunk)
        if im:
            roots.append(int(im.group(1)))
    # XRef stream trailers: /Root inside startxref object
    sx = pdf_bytes.rfind(b"startxref")
    if sx >= 0:
        m = re.search(rb"startxref\s+(\d+)", pdf_bytes[sx:sx + 64])
        if m:
            off = int(m.group(1))
            head = pdf_bytes[off:off + 200]
            om = re.match(rb"(\d+)\s+\d+\s+obj", head)
            if om:
                body = _object_body(pdf_bytes, int(om.group(1)))
                rm = _ROOT_RE.search(body)
                if rm:
                    roots.append(int(rm.group(1)))
                im = _INFO_RE.search(body)
                if im:
                    roots.append(int(im.group(1)))
    # Fallback: Catalog
    cat = re.search(rb"/Type\s*/Catalog", pdf_bytes)
    if cat:
        start = pdf_bytes.rfind(b"obj", 0, cat.start())
        om = re.search(
            rb"(\d+)\s+\d+\s+obj",
            pdf_bytes[max(0, start - 30):cat.start() + 5],
        )
        if om:
            roots.append(int(om.group(1)))
    # unique preserve order
    seen: set[int] = set()
    out: list[int] = []
    for n in roots:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def reachable_object_graph(pdf_bytes: bytes) -> set[int]:
    """Full object graph from trailer /Root and /Info."""
    seen: set[int] = set()
    stack = list(_trailer_roots(pdf_bytes))
    while stack:
        num = stack.pop()
        if num in seen:
            continue
        seen.add(num)
        body = _object_body(pdf_bytes, num)
        if not body:
            continue
        for ref in _REF_RE.finditer(body):
            rn = int(ref.group(1))
            if rn not in seen:
                stack.append(rn)
    return seen


def active_content_xrefs(pdf_bytes: bytes, reachable: set[int]) -> list[int]:
    """Page Contents streams reachable from the page tree."""
    out: list[int] = []
    for num in sorted(reachable):
        body = _object_body(pdf_bytes, num)
        if not body:
            continue
        if b"/Type /Page" not in body and b"/Type/Page" not in body:
            continue
        # skip Pages tree node
        if b"/Type /Pages" in body or b"/Type/Pages" in body:
            continue
        cm = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", body)
        if cm:
            out.append(int(cm.group(1)))
            continue
        am = re.search(rb"/Contents\s*\[(.*?)\]", body, re.S)
        if am:
            for rm in _REF_RE.finditer(am.group(1)):
                out.append(int(rm.group(1)))
    return out


def _decode_flate(raw: bytes) -> bytes | None:
    for variant in (raw, raw.rstrip(b"\r\n"), raw.rstrip(b"\n")):
        try:
            return zlib.decompress(variant)
        except Exception:
            continue
    return None


def _stream_payload(pdf_bytes: bytes, num: int) -> tuple[bytes, bytes] | None:
    """Return (dict_header, decoded_or_raw_bytes)."""
    body = _object_body(pdf_bytes, num)
    if not body or b"stream" not in body:
        return None
    sm = _STREAM_RE.search(body)
    if not sm:
        return None
    header = body[:sm.start()]
    end = body.find(b"endstream", sm.end())
    raw = body[sm.end():end] if end > 0 else body[sm.end():]
    if b"/FlateDecode" in header or b"/Flate" in header:
        dec = _decode_flate(raw)
        if dec is None:
            return None
        return header, dec
    return header, raw


def _is_excluded_stream(header: bytes, decoded: bytes) -> bool:
    h = header.lower()
    if b"/fontfile" in h or b"/subtype /image" in h or b"/subtype/image" in h:
        return True
    if b"/cidset" in h:
        return True
    if b"begincmap" in decoded[:200].lower() or b"begincodespacerange" in decoded[:200]:
        return True
    if decoded[:2] == b"\xff\xd8" or decoded[:4] == b"\x00\x01\x00\x00" or decoded[:4] == b"OTTO":
        return True
    return False


def _bt_et_balanced(decoded: bytes) -> bool:
    bt = len(re.findall(rb"\bBT\b", decoded))
    et = len(re.findall(rb"\bET\b", decoded))
    return bt > 0 and bt == et


def _tj_count(decoded: bytes) -> int:
    return len(re.findall(rb"\bTj\b", decoded)) + len(re.findall(rb"\bTJ\b", decoded))


def _has_tm_td(decoded: bytes) -> bool:
    return bool(re.search(rb"\bTm\b", decoded) or re.search(rb"\bTd\b", decoded))


def _has_font_ops(decoded: bytes) -> bool:
    return bool(re.search(rb"/[A-Za-z][A-Za-z0-9]*\s+[\d.]+\s+Tf", decoded))


def _parse_cmap(data: bytes) -> dict[int, str]:
    text = data.decode("latin1", "replace")
    mapp: dict[int, str] = {}
    for sec in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.S):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", sec.group(1)):
            src, dst = m.group(1), m.group(2)
            cid = int(src[-4:], 16)
            chars = "".join(
                chr(int(dst[i:i + 4], 16))
                for i in range(0, len(dst), 4)
                if i + 4 <= len(dst)
            )
            mapp[cid] = chars
    for sec in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.S):
        for m in re.finditer(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            sec.group(1),
        ):
            start, end, dst = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            if len(dst) != 4:
                continue
            base = int(dst, 16)
            for i, cid in enumerate(range(start, end + 1)):
                mapp[cid] = chr(base + i)
    return mapp


def _page_font_cmaps(pdf_bytes: bytes, reachable: set[int]) -> dict[str, dict[int, str]]:
    """Build resource font name → ToUnicode map from first reachable Page."""
    try:
        import fitz
    except ImportError:
        return {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return {}
    font_cmaps: dict[str, dict[int, str]] = {}
    try:
        if not doc.page_count:
            return {}
        page = doc[0]
        for f in page.get_fonts(full=True) or []:
            refname = f[4]
            xref = f[0]
            font_cmaps[refname] = {}
            try:
                tu = doc.xref_get_key(xref, "ToUnicode")
                if tu and tu[0] == "xref":
                    data = doc.xref_stream(int(tu[1].split()[0])) or b""
                    font_cmaps[refname] = _parse_cmap(data)
            except Exception:
                pass
    finally:
        doc.close()
    return font_cmaps


def decode_content_stream_text(
    decoded: bytes,
    font_cmaps: dict[str, dict[int, str]],
) -> str:
    """Decode Tj/TJ with Type0 Identity-H / ToUnicode / WinAnsi literals."""
    tokens: list[tuple[str, Any]] = []
    i = 0
    n = len(decoded)
    while i < n:
        c = decoded[i:i + 1]
        if c in b" \t\r\n":
            i += 1
            continue
        if c == b"/":
            m = re.match(rb"/([A-Za-z0-9]+)", decoded[i:])
            if not m:
                i += 1
                continue
            tokens.append(("name", m.group(1).decode()))
            i += m.end()
            continue
        if c == b"<":
            if decoded[i:i + 2] == b"<<":
                tokens.append(("op", "<<"))
                i += 2
                continue
            m = re.match(rb"<([0-9A-Fa-f\s]+)>", decoded[i:])
            if m:
                tokens.append(("hex", re.sub(rb"\s+", b"", m.group(1))))
                i += m.end()
                continue
            i += 1
            continue
        if c == b"(":
            j = i + 1
            out = bytearray()
            while j < n:
                ch = decoded[j]
                if ch == 0x5C and j + 1 < n:
                    out.append(decoded[j + 1])
                    j += 2
                    continue
                if ch == 0x29:
                    break
                out.append(ch)
                j += 1
            tokens.append(("str", bytes(out)))
            i = j + 1
            continue
        if c == b"[":
            tokens.append(("op", "["))
            i += 1
            continue
        if c == b"]":
            tokens.append(("op", "]"))
            i += 1
            continue
        m = re.match(rb"[A-Za-z*]+", decoded[i:])
        if m:
            tokens.append(("op", m.group(0).decode()))
            i += m.end()
            continue
        m = re.match(rb"[-+]?\d*\.?\d+", decoded[i:])
        if m:
            tokens.append(("num", m.group(0).decode()))
            i += m.end()
            continue
        i += 1

    def hex_to_text(hx: bytes, font: str) -> str:
        cm = font_cmaps.get(font) or {}
        chars: list[str] = []
        for k in range(0, len(hx), 4):
            chunk = hx[k:k + 4]
            if len(chunk) < 4:
                continue
            cid = int(chunk, 16)
            if cm:
                chars.append(cm.get(cid, ""))
            elif 0x20 <= cid <= 0x7E or 0x400 <= cid <= 0x4FF:
                chars.append(chr(cid))
        return "".join(chars)

    cur_font = "F1"
    out: list[str] = []
    i = 0
    while i < len(tokens):
        kind, val = tokens[i]
        if kind == "op" and val == "Tf" and i >= 2 and tokens[i - 2][0] == "name":
            cur_font = tokens[i - 2][1]
        elif kind == "op" and val == "Tj" and i >= 1:
            prev = tokens[i - 1]
            if prev[0] == "hex":
                out.append(hex_to_text(prev[1], cur_font))
            elif prev[0] == "str":
                out.append(prev[1].decode("latin1", "replace"))
        elif kind == "op" and val == "TJ":
            parts: list[str] = []
            j = i - 1
            while j >= 0 and not (tokens[j][0] == "op" and tokens[j][1] == "["):
                if tokens[j][0] == "hex":
                    parts.append(hex_to_text(tokens[j][1], cur_font))
                elif tokens[j][0] == "str":
                    parts.append(tokens[j][1].decode("latin1", "replace"))
                j -= 1
            out.append("".join(reversed(parts)))
        i += 1
    return "\n".join(x for x in out if x and x.strip())


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ").replace("\u202f", " ")).strip()


def _field_after_label(text: str, label: str) -> str:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    lines = [ln.strip() for ln in raw.splitlines()]
    low_label = label.lower().rstrip(":")
    for i, ln in enumerate(lines):
        if low_label in ln.lower():
            # value on same line after colon
            if ":" in ln:
                after = ln.split(":", 1)[1].strip()
                if after:
                    return _norm_ws(after)
            for nxt in lines[i + 1:i + 4]:
                if not nxt:
                    continue
                if any(a in nxt.lower() for a in _GPB_ANCHORS if a != low_label):
                    # next label — skip empty
                    if len(nxt) < 40 and nxt.endswith(":"):
                        continue
                    # if looks like another label alone
                    if nxt.lower().rstrip(":") in _GPB_ANCHORS:
                        continue
                return _norm_ws(nxt)
    return ""


def parse_gpb_receipt_fields(text: str) -> dict[str, str]:
    """Normalize Gazprombank receipt fields from decoded text."""
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    low = raw.lower()

    def grab(*labels: str) -> str:
        for lab in labels:
            v = _field_after_label(raw, lab)
            if v:
                return v
        return ""

    amount = grab("сумма в валюте зачисления", "сумма:") or grab("сумма")
    # Prefer exact "Сумма:" line over commission labels — refine
    m_amt = re.search(
        r"(?im)^сумма:\s*\n?\s*([\d\s\u00a0]+,\d{2}\s*руб\.?)",
        raw,
    )
    if m_amt:
        amount = _norm_ws(m_amt.group(1))
    else:
        # fallback: line after bare Сумма (not комиссии / с учётом)
        for i, ln in enumerate(raw.splitlines()):
            if re.fullmatch(r"\s*сумма:\s*", ln, re.I) or re.fullmatch(r"\s*сумма\s*", ln, re.I):
                for nxt in raw.splitlines()[i + 1:i + 3]:
                    if re.search(r"\d.*=руб|руб", nxt, re.I) or re.search(r"\d+[.,]\d{2}", nxt):
                        if "комис" in nxt.lower() or "учёт" in nxt.lower():
                            continue
                        amount = _norm_ws(nxt)
                        break

    commission = grab("сумма комиссии")
    total = grab("сумма с учётом комиссии", "сумма с учетом комиссии")
    rrn = grab("rrn")
    if not rrn:
        m = re.search(r"\bRRN:\s*(\d{6,})", raw, re.I)
        if m:
            rrn = m.group(1)
    sbp = grab("номер операции сбп", "номер операции в сбп")
    if not sbp:
        m = re.search(r"\b([AB][0-9A-Z]{31})\b", re.sub(r"\s+", "", raw))
        if m:
            sbp = m.group(1)

    auth = grab("код авторизации/код операции", "код авторизации")
    source = grab("номер источника списания")
    last4 = ""
    digits = re.sub(r"\D", "", source)
    if len(digits) >= 4:
        last4 = digits[-4:]

    # Recipient blocks: last "Получатель" name vs bank-like
    recipients = []
    lines = raw.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower().rstrip(":") == "получатель":
            for nxt in lines[i + 1:i + 3]:
                if nxt.strip():
                    recipients.append(_norm_ws(nxt))
                    break
    recipient_bank = ""
    recipient_name = ""
    if recipients:
        # Heuristic: bank-like if contains Банк / ПСБ / short caps
        for r in recipients:
            if "банк" in r.lower() or r.upper() == r and len(r) <= 12:
                recipient_bank = r
            else:
                recipient_name = r
        if not recipient_bank and recipients:
            recipient_bank = recipients[0]
        if not recipient_name and len(recipients) > 1:
            recipient_name = recipients[-1]

    phone = grab("телефон получателя")
    phone_digits = re.sub(r"\D", "", phone)

    dt = grab("дата и время операции")
    op_type = grab("тип операции")
    status = grab("статус операции")
    currency = grab("валюта зачисления")
    fx = grab("сумма в валюте зачисления")

    return {
        "operation_datetime": dt,
        "operation_type": op_type,
        "status": status,
        "authorization_code": auth,
        "source_last4": last4,
        "recipient_bank": recipient_bank,
        "recipient_phone": phone_digits[-11:] if phone_digits else phone,
        "recipient_name": recipient_name,
        "currency": currency,
        "fx_amount": fx,
        "amount": amount,
        "commission": commission,
        "total": total,
        "rrn": re.sub(r"\D", "", rrn),
        "sbp_operation_id": sbp,
    }


def _anchor_count(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for a in _GPB_ANCHORS if a in low)


def _identity_confirmed(a: dict[str, str], b: dict[str, str]) -> bool:
    same_rrn = bool(a.get("rrn") and a.get("rrn") == b.get("rrn"))
    same_sbp = bool(a.get("sbp_operation_id") and a.get("sbp_operation_id") == b.get("sbp_operation_id"))
    if not (same_rrn or same_sbp):
        return False
    same_auth = bool(
        a.get("authorization_code")
        and a.get("authorization_code") == b.get("authorization_code")
    )
    same_src = bool(a.get("source_last4") and a.get("source_last4") == b.get("source_last4"))
    return same_auth or same_src


def _dynamic_conflicts(a: dict[str, str], b: dict[str, str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for key in _DYNAMIC_FIELDS:
        va, vb = (a.get(key) or "").strip(), (b.get(key) or "").strip()
        if not va or not vb:
            continue
        if va != vb:
            out[key] = {"active": va, "latent": vb}
    return out


def parse_pdf_date(value: str) -> datetime | None:
    m = _PDF_DATE_RE.match((value or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s = map(int, m.groups()[:6])
    tz_raw = m.group(7) or "Z"
    try:
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz_raw and tz_raw not in {"Z", "z"}:
        # e.g. +03'00' or +03
        mm = re.match(r"([+\-])(\d{2})'?(\d{2})?", tz_raw)
        if mm:
            sign = 1 if mm.group(1) == "+" else -1
            off = timedelta(hours=int(mm.group(2)), minutes=int(mm.group(3) or 0))
            dt = dt.replace(tzinfo=timezone(sign * off)).astimezone(timezone.utc)
    return dt


def check_operation_after_pdf_creation(
    text: str,
    creation_date: str = "",
    mod_date: str = "",
) -> Graph003Result:
    """HARD if operation time is >5 minutes after max(CreationDate, ModDate) UTC."""
    res = Graph003Result()
    from ..gpb_profiles import parse_operation_datetime

    op = parse_operation_datetime(text)
    if not op:
        res.stats["creation_check"] = "no_operation_datetime"
        return res
    # Operation printed as MSK (UTC+3)
    op_utc = op.replace(tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc)

    cands = [parse_pdf_date(creation_date), parse_pdf_date(mod_date)]
    cands = [c for c in cands if c is not None]
    if not cands:
        res.stats["creation_check"] = "no_metadata"
        return res
    meta_max = max(cands)
    delta = (op_utc - meta_max).total_seconds()
    res.stats["creation_check"] = {
        "operation_utc": op_utc.isoformat(),
        "meta_max_utc": meta_max.isoformat(),
        "delta_sec": delta,
    }
    if delta > 5 * 60:
        res.hard = True
        res.score = SCORE
        res.flags.append(
            f"[{CREATION_HARD_CODE}] операция {op_utc.isoformat()} позже "
            f"PDF metadata {meta_max.isoformat()} на {int(delta)} сек (>5 мин)"
        )
    return res


def run_g_graph_003(pdf_bytes: bytes, visible_text: str) -> Graph003Result:
    res = Graph003Result()
    if not pdf_bytes:
        return res

    all_objs = _all_object_nums(pdf_bytes)
    reachable = reachable_object_graph(pdf_bytes)
    orphans = all_objs - reachable
    active_xrefs = active_content_xrefs(pdf_bytes, reachable)
    res.stats.update({
        "object_total": len(all_objs),
        "reachable": len(reachable),
        "orphan_objects": len(orphans),
        "orphan_list": sorted(orphans)[:40],
        "active_content_xrefs": active_xrefs,
    })

    font_cmaps = _page_font_cmaps(pdf_bytes, reachable)
    active_fields = parse_gpb_receipt_fields(visible_text)
    res.stats["active_fields"] = active_fields

    candidates: list[dict[str, Any]] = []
    for num in sorted(orphans):
        payload = _stream_payload(pdf_bytes, num)
        if not payload:
            continue
        header, decoded = payload
        if _is_excluded_stream(header, decoded):
            continue
        if not (500 <= len(decoded) <= 30000):
            continue
        if not _bt_et_balanced(decoded):
            continue
        if _tj_count(decoded) < 8:
            continue
        if not _has_tm_td(decoded) or not _has_font_ops(decoded):
            continue
        text = decode_content_stream_text(decoded, font_cmaps)
        if _anchor_count(text) < 4:
            continue
        fields = parse_gpb_receipt_fields(text)
        candidates.append({
            "xref": num,
            "decoded_len": len(decoded),
            "decoded_sha256": _sha(decoded),
            "text_preview": text[:240],
            "fields": fields,
            "anchor_count": _anchor_count(text),
        })

    res.stats["orphan_candidate_xrefs"] = [c["xref"] for c in candidates]
    res.stats["orphan_candidates"] = [
        {
            "xref": c["xref"],
            "decoded_sha256": c["decoded_sha256"],
            "decoded_len": c["decoded_len"],
            "fields": c["fields"],
        }
        for c in candidates
    ]

    if not candidates:
        if orphans:
            res.diagnostics.append(
                "[G-GRAPH-002] orphan objects without GPB latent receipt candidates"
            )
        return res

    for cand in candidates:
        latent = cand["fields"]
        if not _identity_confirmed(active_fields, latent):
            continue
        conflicts = _dynamic_conflicts(active_fields, latent)
        if not conflicts:
            continue
        stable = {}
        for key in ("rrn", "sbp_operation_id", "authorization_code", "source_last4"):
            if active_fields.get(key) and active_fields.get(key) == latent.get(key):
                stable[key] = active_fields[key]
        res.hard = True
        res.score = SCORE
        detail = (
            f"{RULE_ID}: latent content xref={cand['xref']} shares transaction "
            f"identity {stable} but conflicts on {sorted(conflicts)}"
        )
        res.flags.append(f"[{HARD_CODE}] {detail}")
        res.stats.update({
            "stable_identity_fields": stable,
            "conflict_groups": conflicts,
            "latent_xref": cand["xref"],
            "latent_decoded_sha256": cand["decoded_sha256"],
            "active_version": {k: active_fields.get(k) for k in list(conflicts) + list(stable)},
            "latent_version": {k: latent.get(k) for k in list(conflicts) + list(stable)},
        })
        break

    return res
