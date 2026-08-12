"""File / semantic / assembly known-fake signature channels for VTB v2."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zlib
from dataclasses import dataclass, field

from .known_signatures import (
    VTB_KNOWN_FAKE_ASSEMBLY_SHA256,
    VTB_KNOWN_FAKE_FILE_SHA256,
    VTB_KNOWN_FAKE_SEMANTIC_SHA256,
)
from .subtypes import normalize_text
from .types import VtbFlag

_HYPHENS = (
    "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212",
    "\uFE58", "\uFE63", "\uFF0D",
)


@dataclass
class SignatureResult:
    flags: list[VtbFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    series_hit: bool = False


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _flag(code: str, detail: str) -> VtbFlag:
    return VtbFlag(code=code, detail=detail, tier="KNOWN", rule_id=code)


def normalize_semantic_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\xa0", " ").replace("\u202f", " ")
    for h in _HYPHENS:
        t = t.replace(h, "-")
    lines = t.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if i + 1 < len(lines):
            joined = re.sub(r"[\t \n\r]+", "", ln + lines[i + 1])
            if re.fullmatch(r"[AB][0-9A-Z]{31}", joined):
                out.append(joined)
                i += 2
                continue
        out.append(ln)
        i += 1
    t = "\n".join(out)
    t = re.sub(r"[ \t]+", " ", t)
    return "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())


def semantic_sha256(text: str) -> str:
    return _sha(normalize_semantic_text(text))


def _dec_stream(body: bytes) -> bytes | None:
    sm = re.search(rb"stream\r?\n(.*?)\n?endstream", body, re.S)
    if not sm:
        return None
    raw = sm.group(1)
    try:
        return zlib.decompress(raw.rstrip(b"\r\n"))
    except Exception:
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw


def _norm_w(w: bytes) -> bytes:
    pretty = re.sub(rb"\[\s*", b"[ ", w)
    pretty = re.sub(rb"\s*\]", b" ]", pretty)
    pretty = re.sub(rb"\s+", b" ", pretty.strip())
    return pretty


def _balanced_array(data: bytes, start: int) -> bytes:
    depth = 0
    for i in range(start, len(data)):
        c = data[i:i + 1]
        if c == b"[":
            depth += 1
        elif c == b"]":
            depth -= 1
            if depth == 0:
                return data[start:i + 1]
    return b""


def extract_assembly_components(pdf_bytes: bytes) -> dict[str, str]:
    """Object-graph roles → decoded SHA-256 components."""
    content = b""
    touni = b""
    ff2 = b""
    cid = b""
    w = b""

    m = re.search(rb"/Contents\s+(\d+)\s+0\s+R", pdf_bytes)
    if m:
        om = re.search(
            rf"{int(m.group(1))}\s+0\s+obj(.*?)endobj".encode(),
            pdf_bytes, re.S,
        )
        if om:
            content = _dec_stream(om.group(1)) or b""

    for om in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", pdf_bytes, re.S):
        body = om.group(2)
        if b"/Subtype /Type0" not in body and b"/Subtype/Type0" not in body:
            continue
        tm = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if tm:
            ob = re.search(
                rf"{int(tm.group(1))}\s+0\s+obj(.*?)endobj".encode(),
                pdf_bytes, re.S,
            )
            if ob:
                touni = _dec_stream(ob.group(1)) or b""
        dm = re.search(rb"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", body)
        if not dm:
            break
        dob = re.search(
            rf"{int(dm.group(1))}\s+0\s+obj(.*?)endobj".encode(),
            pdf_bytes, re.S,
        )
        if not dob:
            break
        dbody = dob.group(1)
        wm = re.search(rb"/W\s*\[", dbody)
        if wm:
            w = _balanced_array(dbody, wm.end() - 1)
        cm = re.search(rb"/CIDToGIDMap\s+(\d+)\s+0\s+R", dbody)
        if cm:
            cob = re.search(
                rf"{int(cm.group(1))}\s+0\s+obj(.*?)endobj".encode(),
                pdf_bytes, re.S,
            )
            if cob:
                cid = _dec_stream(cob.group(1)) or b""
        elif re.search(rb"/CIDToGIDMap\s*/Identity", dbody):
            cid = b"Identity"
        fdm = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", dbody)
        if fdm:
            fdob = re.search(
                rf"{int(fdm.group(1))}\s+0\s+obj(.*?)endobj".encode(),
                pdf_bytes, re.S,
            )
            if fdob:
                ffm = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", fdob.group(1))
                if ffm:
                    fob = re.search(
                        rf"{int(ffm.group(1))}\s+0\s+obj(.*?)endobj".encode(),
                        pdf_bytes, re.S,
                    )
                    if fob:
                        ff2 = _dec_stream(fob.group(1)) or b""
        break

    # Fallback: locate CIDToGIDMap stream object by name in graph
    if not cid:
        for om in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", pdf_bytes, re.S):
            body = om.group(2)
            if b"/CIDToGIDMap" in body:
                continue
        # Heuristic: stream whose decoded length is even & starts with NULs
        for om in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", pdf_bytes, re.S):
            body = om.group(2)
            if b"/FontFile2" in body or b"/Subtype /Image" in body:
                continue
            if b"/Filter" not in body or b"stream" not in body:
                continue
            # referenced as CIDToGIDMap elsewhere
            onum = om.group(1).decode()
            if re.search(rf"/CIDToGIDMap\s+{onum}\s+0\s+R".encode(), pdf_bytes):
                cid = _dec_stream(body) or b""
                break

    return {
        "content": _sha(content),
        "tounicode": _sha(touni),
        "cidtogid": _sha(cid),
        "fontfile2": _sha(ff2),
        "w": _sha(_norm_w(w) if w else b""),
    }


def assembly_sha256(pdf_bytes: bytes) -> tuple[str, dict[str, str]]:
    components = extract_assembly_components(pdf_bytes)
    blob = json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(blob), components


def check_known_signatures(
    pdf_bytes: bytes,
    text: str,
    *,
    file_hash: str = "",
    sbp_known_hit: bool = False,
) -> SignatureResult:
    """File / semantic / assembly are alternative channels of one fake series."""
    res = SignatureResult()
    if not file_hash:
        file_hash = _sha(pdf_bytes)
    res.stats["file_sha256"] = file_hash

    sem = semantic_sha256(text)
    asm, comps = assembly_sha256(pdf_bytes)
    res.stats["semantic_sha256"] = sem
    res.stats["assembly_sha256"] = asm
    res.stats["assembly_components"] = comps

    # If SBP linked/tail already matched this series, skip duplicate channels.
    if sbp_known_hit:
        res.series_hit = True
        res.stats["skipped_channels"] = "sbp_series_already_matched"
        return res

    hit = False
    if file_hash in VTB_KNOWN_FAKE_FILE_SHA256:
        hit = True
        res.flags.append(_flag(
            "VTB_KNOWN_FILE_SIGNATURE",
            f"file SHA-256 совпал с известной фейковой серией ({file_hash[:16]}…)",
        ))
    elif sem in VTB_KNOWN_FAKE_SEMANTIC_SHA256:
        hit = True
        res.flags.append(_flag(
            "VTB_KNOWN_SEMANTIC_SIGNATURE",
            f"semantic SHA-256 совпал с известной фейковой серией ({sem[:16]}…)",
        ))
    elif asm in VTB_KNOWN_FAKE_ASSEMBLY_SHA256:
        hit = True
        res.flags.append(_flag(
            "VTB_KNOWN_ASSEMBLY_SIGNATURE",
            f"assembly SHA-256 совпал с известной фейковой серией ({asm[:16]}…)",
        ))

    res.series_hit = hit
    return res
