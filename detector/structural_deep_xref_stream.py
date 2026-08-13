"""Deep classic/xref-stream semantics + stream /Length contract.

Findings start as diagnostics. Codes enter ENABLED_STRUCTURAL_HARD only after
zero-FP genuine corpus gate (see tools/_structural_deep_fp_gate.py).
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Any

# Codes with 0 FP on genuine corpus (Desktop/чеки, 497 PDFs, 2026-08-13 gate).
# SFNT_* and CRITICAL_INDIRECT_REFERENCE_BROKEN stay diagnostic (genuine drift / objstm).
ENABLED_STRUCTURAL_HARD: frozenset[str] = frozenset({
    "XREF_ENTRY_OBJECT_MISMATCH",
    "XREF_GENERATION_MISMATCH",
    "XREF_SUBSECTION_INVALID",
    "XREF_SIZE_CONTRADICTION",
    "XREF_DUPLICATE_LIVE_MAPPING",
    "XREF_OFFSET_INVALID",
    "STREAM_LENGTH_REFERENCE_INVALID",
    "STREAM_LENGTH_TYPE_INVALID",
    "STREAM_LENGTH_BOUNDARY_CONTRADICTION",
    "STREAM_ENDSTREAM_CONTRADICTION",
    "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT",
    "PAGETREE_PARENT_CONTRADICTION",
    "PAGETREE_COUNT_CONTRADICTION",
    "PAGETREE_CYCLE",
    "PAGE_CONTENT_REFERENCE_INVALID",
    "INDIRECT_REFERENCE_GENERATION_MISMATCH",
    "PDF_CRITICAL_PARSE_AMBIGUITY",
})

_STARTXREF_RE = re.compile(rb"startxref\s+(\d+)")
_OBJ_HEAD_RE = re.compile(rb"^(\d+)\s+(\d+)\s+obj\b")
_OBJ_ANY_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_SIZE_RE = re.compile(rb"/Size\s+(\d+)")
_W_RE = re.compile(rb"/W\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]")
_INDEX_RE = re.compile(rb"/Index\s*\[([^\]]*)\]")
_LENGTH_DIRECT_RE = re.compile(rb"/Length\s+(\d+)(?!\s+\d+\s+R)")
_LENGTH_INDIRECT_RE = re.compile(rb"/Length\s+(\d+)\s+(\d+)\s+R")
_INT_OBJ_RE = re.compile(rb"^(\d+)\s+(\d+)\s+obj\s+(\d+)\s+endobj", re.M)


@dataclass
class StructFinding:
    code: str
    detail: str
    object_number: int | None = None
    generation: int | None = None
    offset: int | None = None
    expected: str = ""
    actual: str = ""
    parser_stage: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "object_number": self.object_number,
            "generation": self.generation,
            "offset": self.offset,
            "expected": self.expected,
            "actual": self.actual,
            "parser_stage": self.parser_stage,
        }


@dataclass
class DeepAuditResult:
    findings: list[StructFinding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def add(self, finding: StructFinding) -> None:
        self.findings.append(finding)

    @property
    def hard_findings(self) -> list[StructFinding]:
        return [f for f in self.findings if f.code in ENABLED_STRUCTURAL_HARD]

    @property
    def diagnostic_findings(self) -> list[StructFinding]:
        return [f for f in self.findings if f.code not in ENABLED_STRUCTURAL_HARD]


def set_enabled_structural_hard(codes: frozenset[str] | set[str]) -> None:
    """Test/gate helper — mutates module-level enable set."""
    global ENABLED_STRUCTURAL_HARD
    ENABLED_STRUCTURAL_HARD = frozenset(codes)


def _read_be(data: bytes, nbytes: int) -> int:
    if nbytes <= 0:
        return 0
    if len(data) < nbytes:
        raise ValueError("short field")
    v = 0
    for b in data[:nbytes]:
        v = (v << 8) | b
    return v


def index_indirect_objects(pdf_bytes: bytes) -> dict[tuple[int, int], int]:
    """Map (object_number, generation) → byte offset of 'N G obj'."""
    out: dict[tuple[int, int], int] = {}
    for m in _OBJ_ANY_RE.finditer(pdf_bytes):
        key = (int(m.group(1)), int(m.group(2)))
        # First occurrence wins for body location; duplicates handled elsewhere.
        out.setdefault(key, m.start())
    return out


def _object_at(pdf_bytes: bytes, offset: int) -> tuple[int, int] | None:
    if offset < 0 or offset >= len(pdf_bytes):
        return None
    m = _OBJ_HEAD_RE.match(pdf_bytes[offset : offset + 48])
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _trailer_dict_region(pdf_bytes: bytes, xref_off: int) -> bytes:
    trailer = pdf_bytes.find(b"trailer", xref_off)
    if trailer < 0:
        # xref-stream embeds trailer keys in the object dict
        return pdf_bytes[xref_off : xref_off + 800]
    end = pdf_bytes.find(b"startxref", trailer)
    if end < 0:
        end = min(len(pdf_bytes), trailer + 2000)
    return pdf_bytes[trailer:end]


def _parse_classic_subsections(
    body: bytes,
) -> tuple[list[tuple[int, int, list[tuple[int, int, bytes]]]], list[str]]:
    """Return (subsections, errors).

    Each subsection: (first_object, declared_count, entries[(off, gen, nf), ...]).
    """
    errors: list[str] = []
    if not body.startswith(b"xref"):
        return [], ["classic xref body missing xref keyword"]
    pos = 4
    while pos < len(body) and body[pos : pos + 1] in b"\r\n \t":
        pos += 1
    subsections: list[tuple[int, int, list[tuple[int, int, bytes]]]] = []
    while pos < len(body):
        # stop at trailer-ish
        if body[pos : pos + 7] == b"trailer":
            break
        hm = re.match(rb"(\d+)\s+(\d+)\s*\r?\n", body[pos:])
        if not hm:
            break
        first = int(hm.group(1))
        count = int(hm.group(2))
        pos += hm.end()
        entries: list[tuple[int, int, bytes]] = []
        for _ in range(count):
            if pos + 18 > len(body):
                errors.append(
                    f"subsection {first}/{count}: truncated entries "
                    f"(got {len(entries)})"
                )
                break
            line = body[pos : pos + 20]
            em = re.match(rb"(\d{10}) (\d{5}) ([nf])[ ]?\r?\n?", line)
            if not em:
                # try looser
                em = re.match(rb"(\d{10}) (\d{5}) ([nf])", body[pos : pos + 18])
                if not em:
                    errors.append(
                        f"subsection {first}/{count}: malformed entry at +{pos}"
                    )
                    break
                pos += 18
                while pos < len(body) and body[pos : pos + 1] in b"\r\n ":
                    pos += 1
            else:
                pos += em.end()
            entries.append((int(em.group(1)), int(em.group(2)), em.group(3)))
        if len(entries) != count:
            errors.append(
                f"subsection first={first} count={count} actual_entries={len(entries)}"
            )
        subsections.append((first, count, entries))
    return subsections, errors


def audit_xref_deep(pdf_bytes: bytes) -> DeepAuditResult:
    res = DeepAuditResult()
    b = pdf_bytes
    sx = b.rfind(b"startxref")
    if sx < 0:
        res.stats["xref_deep"] = "no_startxref"
        return res
    m = _STARTXREF_RE.search(b, sx)
    if not m:
        res.stats["xref_deep"] = "bad_startxref"
        return res
    off = int(m.group(1))
    res.stats["startxref"] = off
    if off <= 0 or off >= len(b):
        res.add(StructFinding(
            code="XREF_OFFSET_INVALID",
            detail=f"startxref={off} out of file bounds len={len(b)}",
            offset=off,
            expected=f"0..{len(b)-1}",
            actual=str(off),
            parser_stage="xref_deep.startxref",
        ))
        return res

    head = b[off : off + 32]
    if head[:4] == b"xref":
        _audit_classic_xref(b, off, res)
    elif re.match(rb"\d+\s+\d+\s+obj", head):
        _audit_xref_stream(b, off, res)
    else:
        res.add(StructFinding(
            code="XREF_OFFSET_INVALID",
            detail="startxref does not point to xref or xref-stream",
            offset=off,
            parser_stage="xref_deep.head",
        ))
    return res


def _audit_classic_xref(b: bytes, off: int, res: DeepAuditResult) -> None:
    trailer = b.find(b"trailer", off)
    if trailer < 0:
        res.add(StructFinding(
            code="XREF_SUBSECTION_INVALID",
            detail="classic xref without trailer",
            offset=off,
            parser_stage="xref_deep.classic",
        ))
        return
    body = b[off:trailer]
    subsections, serr = _parse_classic_subsections(body)
    for e in serr:
        res.add(StructFinding(
            code="XREF_SUBSECTION_INVALID",
            detail=e,
            offset=off,
            parser_stage="xref_deep.classic.subsection",
        ))

    live_map: dict[int, tuple[int, int, int]] = {}  # objnum -> (offset, gen, first)
    max_obj = -1
    for first, count, entries in subsections:
        for i, (eoff, gen, nf) in enumerate(entries):
            objnum = first + i
            max_obj = max(max_obj, objnum)
            if nf == b"f":
                continue
            if eoff <= 0 or eoff >= len(b):
                res.add(StructFinding(
                    code="XREF_OFFSET_INVALID",
                    detail=f"live xref obj {objnum} offset {eoff} out of bounds",
                    object_number=objnum,
                    generation=gen,
                    offset=eoff,
                    parser_stage="xref_deep.classic.bounds",
                ))
                continue
            at = _object_at(b, eoff)
            if at is None:
                res.add(StructFinding(
                    code="XREF_OFFSET_INVALID",
                    detail=(
                        f"xref obj {objnum} gen {gen} offset {eoff} "
                        f"does not start an indirect object"
                    ),
                    object_number=objnum,
                    generation=gen,
                    offset=eoff,
                    expected=f"{objnum} {gen} obj",
                    actual=repr(b[eoff : eoff + 24]),
                    parser_stage="xref_deep.classic.not_obj",
                ))
                continue
            onum, ogen = at
            if onum != objnum:
                res.add(StructFinding(
                    code="XREF_ENTRY_OBJECT_MISMATCH",
                    detail=(
                        f"xref slot {objnum} points to offset {eoff} which is "
                        f"object {onum} {ogen} obj"
                    ),
                    object_number=objnum,
                    generation=gen,
                    offset=eoff,
                    expected=str(objnum),
                    actual=str(onum),
                    parser_stage="xref_deep.classic.objnum",
                ))
            if ogen != gen:
                res.add(StructFinding(
                    code="XREF_GENERATION_MISMATCH",
                    detail=(
                        f"xref slot {objnum} gen={gen} but object header gen={ogen} "
                        f"at offset {eoff}"
                    ),
                    object_number=objnum,
                    generation=gen,
                    offset=eoff,
                    expected=str(gen),
                    actual=str(ogen),
                    parser_stage="xref_deep.classic.generation",
                ))
            if objnum in live_map:
                prev_off, prev_gen, _ = live_map[objnum]
                if prev_off != eoff or prev_gen != gen:
                    # Same obj number mapped to incompatible locations
                    at_prev = _object_at(b, prev_off)
                    if at_prev and at != at_prev:
                        res.add(StructFinding(
                            code="XREF_DUPLICATE_LIVE_MAPPING",
                            detail=(
                                f"object {objnum} has incompatible live xref mappings "
                                f"off={prev_off}/{eoff}"
                            ),
                            object_number=objnum,
                            offset=eoff,
                            expected=str(prev_off),
                            actual=str(eoff),
                            parser_stage="xref_deep.classic.dup_live",
                        ))
            else:
                live_map[objnum] = (eoff, gen, first)

    # /Size vs object number space
    tdict = _trailer_dict_region(b, off)
    sm = _SIZE_RE.search(tdict)
    if sm:
        size = int(sm.group(1))
        res.stats["trailer_size"] = size
        if max_obj >= 0 and size <= max_obj:
            res.add(StructFinding(
                code="XREF_SIZE_CONTRADICTION",
                detail=f"/Size {size} but xref covers object {max_obj}",
                expected=f">={max_obj + 1}",
                actual=str(size),
                parser_stage="xref_deep.classic.size",
            ))
        # object 0 free semantics: first subsection often starts at 0
        for first, count, entries in subsections:
            if first == 0 and count > 0 and entries:
                eoff, gen, nf = entries[0]
                if nf != b"f":
                    res.add(StructFinding(
                        code="XREF_SUBSECTION_INVALID",
                        detail="object 0 must be free (f) in classic xref",
                        object_number=0,
                        generation=gen,
                        parser_stage="xref_deep.classic.obj0",
                    ))

    # overlapping subsections on same object numbers with conflicting live data
    covered: dict[int, tuple[int, int, bytes]] = {}
    for first, count, entries in subsections:
        for i, ent in enumerate(entries):
            objnum = first + i
            if objnum in covered and covered[objnum] != ent and ent[2] == b"n":
                if covered[objnum][2] == b"n" and (
                    covered[objnum][0] != ent[0] or covered[objnum][1] != ent[1]
                ):
                    res.add(StructFinding(
                        code="XREF_DUPLICATE_LIVE_MAPPING",
                        detail=(
                            f"overlapping xref subsections remap live object {objnum}"
                        ),
                        object_number=objnum,
                        parser_stage="xref_deep.classic.overlap",
                    ))
            covered[objnum] = ent

    res.stats["classic_subsections"] = len(subsections)
    res.stats["classic_live"] = len(live_map)


def _audit_xref_stream(b: bytes, off: int, res: DeepAuditResult) -> None:
    try:
        om = re.match(rb"(\d+)\s+(\d+)\s+obj", b[off : off + 40])
        if not om:
            res.add(StructFinding(
                code="XREF_SUBSECTION_INVALID",
                detail="xref-stream object header invalid",
                offset=off,
                parser_stage="xref_deep.stream.head",
            ))
            return
        stream_kw = b.find(b"stream", off)
        if stream_kw < 0:
            res.add(StructFinding(
                code="XREF_SUBSECTION_INVALID",
                detail="xref-stream missing stream keyword",
                offset=off,
                parser_stage="xref_deep.stream",
            ))
            return
        hdr = b[off:stream_kw]
        cs = stream_kw + 6
        if b[cs : cs + 2] == b"\r\n":
            cs += 2
        elif b[cs : cs + 1] == b"\n":
            cs += 1
        es = b.find(b"endstream", cs)
        if es < 0:
            res.add(StructFinding(
                code="XREF_SUBSECTION_INVALID",
                detail="xref-stream missing endstream",
                offset=off,
                parser_stage="xref_deep.stream",
            ))
            return
        # Prefer declared /Length when present
        lm = _LENGTH_DIRECT_RE.search(hdr)
        lim = _LENGTH_INDIRECT_RE.search(hdr)
        raw = b[cs:es].rstrip(b"\r\n")
        if lm and not lim:
            declared = int(lm.group(1))
            raw = b[cs : cs + declared]
        try:
            dec = zlib.decompress(raw)
        except Exception:
            # Some xref streams are uncompressed
            dec = raw

        sm = _SIZE_RE.search(hdr)
        wm = _W_RE.search(hdr)
        if not wm:
            res.stats["xref_stream"] = "no_W"
            return
        w = [int(wm.group(i)) for i in range(1, 4)]
        row = w[0] + w[1] + w[2]
        if row <= 0:
            res.add(StructFinding(
                code="XREF_SUBSECTION_INVALID",
                detail=f"invalid /W {w}",
                parser_stage="xref_deep.stream.W",
            ))
            return

        index_pairs: list[tuple[int, int]] = []
        idx_m = _INDEX_RE.search(hdr)
        if idx_m:
            parts = [int(x) for x in idx_m.group(1).split() if x.strip().isdigit() or x.strip().lstrip("-").isdigit()]
            # Actually split on whitespace for ints
            parts = [int(x) for x in re.findall(rb"\d+", idx_m.group(1))]
            if len(parts) % 2 != 0 or not parts:
                res.add(StructFinding(
                    code="XREF_SUBSECTION_INVALID",
                    detail=f"malformed /Index {idx_m.group(1)!r}",
                    expected="pairs of first count",
                    actual=repr(idx_m.group(1)),
                    parser_stage="xref_deep.stream.Index",
                ))
            else:
                for i in range(0, len(parts), 2):
                    index_pairs.append((parts[i], parts[i + 1]))
        else:
            size = int(sm.group(1)) if sm else 0
            index_pairs = [(0, size)]

        total_rows = sum(c for _, c in index_pairs)
        need = total_rows * row
        if len(dec) < need:
            res.add(StructFinding(
                code="XREF_SUBSECTION_INVALID",
                detail=(
                    f"xref-stream decoded length {len(dec)} < need {need} "
                    f"(rows={total_rows} row={row})"
                ),
                expected=str(need),
                actual=str(len(dec)),
                parser_stage="xref_deep.stream.len",
            ))
            return

        live_map: dict[int, tuple[int, int]] = {}
        max_obj = -1
        cursor = 0
        for first, count in index_pairs:
            for i in range(count):
                objnum = first + i
                max_obj = max(max_obj, objnum)
                chunk = dec[cursor : cursor + row]
                cursor += row
                try:
                    ftype = _read_be(chunk[0 : w[0]], w[0]) if w[0] else 1
                    f1 = _read_be(chunk[w[0] : w[0] + w[1]], w[1]) if w[1] else 0
                    f2 = _read_be(
                        chunk[w[0] + w[1] : w[0] + w[1] + w[2]], w[2]
                    ) if w[2] else 0
                except ValueError:
                    res.add(StructFinding(
                        code="XREF_SUBSECTION_INVALID",
                        detail=f"short xref-stream row for object {objnum}",
                        object_number=objnum,
                        parser_stage="xref_deep.stream.row",
                    ))
                    continue

                if ftype == 0:
                    continue
                if ftype == 1:
                    eoff, gen = f1, f2
                    if eoff <= 0 or eoff >= len(b):
                        res.add(StructFinding(
                            code="XREF_OFFSET_INVALID",
                            detail=f"xref-stream type1 obj {objnum} offset {eoff} OOB",
                            object_number=objnum,
                            generation=gen,
                            offset=eoff,
                            parser_stage="xref_deep.stream.type1.bounds",
                        ))
                        continue
                    at = _object_at(b, eoff)
                    if at is None:
                        res.add(StructFinding(
                            code="XREF_OFFSET_INVALID",
                            detail=(
                                f"xref-stream type1 obj {objnum} offset {eoff} "
                                f"not an object header"
                            ),
                            object_number=objnum,
                            generation=gen,
                            offset=eoff,
                            parser_stage="xref_deep.stream.type1.not_obj",
                        ))
                        continue
                    onum, ogen = at
                    if onum != objnum:
                        res.add(StructFinding(
                            code="XREF_ENTRY_OBJECT_MISMATCH",
                            detail=(
                                f"xref-stream slot {objnum} → offset {eoff} is "
                                f"{onum} {ogen} obj"
                            ),
                            object_number=objnum,
                            generation=gen,
                            offset=eoff,
                            expected=str(objnum),
                            actual=str(onum),
                            parser_stage="xref_deep.stream.type1.objnum",
                        ))
                    if ogen != gen:
                        res.add(StructFinding(
                            code="XREF_GENERATION_MISMATCH",
                            detail=(
                                f"xref-stream slot {objnum} gen={gen} header gen={ogen}"
                            ),
                            object_number=objnum,
                            generation=gen,
                            offset=eoff,
                            expected=str(gen),
                            actual=str(ogen),
                            parser_stage="xref_deep.stream.type1.gen",
                        ))
                    if objnum in live_map and live_map[objnum] != (eoff, gen):
                        res.add(StructFinding(
                            code="XREF_DUPLICATE_LIVE_MAPPING",
                            detail=f"xref-stream duplicate live mapping for {objnum}",
                            object_number=objnum,
                            parser_stage="xref_deep.stream.dup",
                        ))
                    live_map[objnum] = (eoff, gen)
                elif ftype == 2:
                    # object-stream reference: field1 = objstm number, field2 = index
                    stm_num, idx = f1, f2
                    # Existence of object stream checked lightly
                    if not re.search(rf"{stm_num}\s+\d+\s+obj".encode(), b):
                        res.add(StructFinding(
                            code="CRITICAL_INDIRECT_REFERENCE_BROKEN",
                            detail=(
                                f"xref-stream type2 obj {objnum} references missing "
                                f"object stream {stm_num} (index {idx})"
                            ),
                            object_number=objnum,
                            expected=f"objstm {stm_num}",
                            actual="missing",
                            parser_stage="xref_deep.stream.type2",
                        ))
                else:
                    res.add(StructFinding(
                        code="XREF_SUBSECTION_INVALID",
                        detail=f"xref-stream unknown type {ftype} for obj {objnum}",
                        object_number=objnum,
                        parser_stage="xref_deep.stream.type",
                    ))

        if sm:
            size = int(sm.group(1))
            if max_obj >= 0 and size <= max_obj:
                res.add(StructFinding(
                    code="XREF_SIZE_CONTRADICTION",
                    detail=f"xref-stream /Size {size} but covers object {max_obj}",
                    expected=f">={max_obj + 1}",
                    actual=str(size),
                    parser_stage="xref_deep.stream.size",
                ))
        res.stats["xref_stream_rows"] = total_rows
        res.stats["xref_stream_index_pairs"] = len(index_pairs)
    except Exception as exc:
        res.add(StructFinding(
            code="XREF_SUBSECTION_INVALID",
            detail=f"xref-stream parse error: {exc}",
            parser_stage="xref_deep.stream.exc",
        ))


def _resolve_length_value(
    hdr: bytes,
    pdf_bytes: bytes,
    obj_index: dict[tuple[int, int], int],
) -> tuple[int | None, StructFinding | None, str]:
    """Return (length, error_finding, mode)."""
    lim = _LENGTH_INDIRECT_RE.search(hdr)
    if lim:
        n, g = int(lim.group(1)), int(lim.group(2))
        key = (n, g)
        if key not in obj_index:
            # generation-specific miss: any gen of n?
            any_n = [k for k in obj_index if k[0] == n]
            if not any_n:
                return None, StructFinding(
                    code="STREAM_LENGTH_REFERENCE_INVALID",
                    detail=f"/Length {n} {g} R references missing object",
                    object_number=n,
                    generation=g,
                    expected=f"{n} {g} R",
                    actual="missing",
                    parser_stage="stream_length.indirect.missing",
                ), "indirect"
            return None, StructFinding(
                code="STREAM_LENGTH_REFERENCE_INVALID",
                detail=(
                    f"/Length {n} {g} R generation mismatch; present gens="
                    f"{sorted({k[1] for k in any_n})}"
                ),
                object_number=n,
                generation=g,
                parser_stage="stream_length.indirect.gen",
            ), "indirect"
        start = obj_index[key]
        # Parse integer object body
        chunk = pdf_bytes[start : start + 200]
        im = re.match(rb"\d+\s+\d+\s+obj\s+(\d+)\s+endobj", chunk)
        if not im:
            # allow whitespace/newlines
            im = re.search(rb"obj\s+(\d+)\s+endobj", chunk)
        if not im:
            # maybe not a bare int
            if re.search(rb"obj\s+<<", chunk) or re.search(rb"obj\s+\[", chunk):
                return None, StructFinding(
                    code="STREAM_LENGTH_TYPE_INVALID",
                    detail=f"/Length {n} {g} R does not resolve to an integer",
                    object_number=n,
                    generation=g,
                    parser_stage="stream_length.indirect.type",
                ), "indirect"
            return None, StructFinding(
                code="STREAM_LENGTH_TYPE_INVALID",
                detail=f"/Length {n} {g} R integer value not parseable",
                object_number=n,
                generation=g,
                parser_stage="stream_length.indirect.parse",
            ), "indirect"
        return int(im.group(1)), None, "indirect"

    lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", hdr)
    if lm:
        return int(lm.group(1)), None, "direct"
    return None, None, "none"


def audit_stream_length_contract(pdf_bytes: bytes) -> DeepAuditResult:
    """Per-object stream /Length contract — no (len, prefix) dedupe."""
    res = DeepAuditResult()
    obj_index = index_indirect_objects(pdf_bytes)
    checked = 0
    # Walk every object that contains a stream keyword after its dict
    for (onum, ogen), start in sorted(obj_index.items(), key=lambda x: x[1]):
        # Bound object roughly to next endobj
        endobj = pdf_bytes.find(b"endobj", start)
        if endobj < 0:
            continue
        body = pdf_bytes[start:endobj]
        sm = re.search(rb"stream(\r\n|\n|\r)", body)
        if not sm:
            continue
        hdr = body[: sm.start()]
        # Skip if this looks like nested mention only without dict
        if b"/Length" not in hdr and b"stream" not in body[: sm.start() + 10]:
            continue
        payload_start = start + sm.end()
        length, err, mode = _resolve_length_value(hdr, pdf_bytes, obj_index)
        if err is not None:
            err.object_number = err.object_number if err.object_number is not None else onum
            err.generation = err.generation if err.generation is not None else ogen
            err.offset = payload_start
            res.add(err)
            checked += 1
            continue
        if length is None:
            continue
        checked += 1
        es = pdf_bytes.find(b"endstream", payload_start)
        if es < 0:
            res.add(StructFinding(
                code="STREAM_LENGTH_BOUNDARY_CONTRADICTION",
                detail=f"obj {onum} {ogen}: /Length={length} but no endstream",
                object_number=onum,
                generation=ogen,
                offset=payload_start,
                expected=str(length),
                actual="no endstream",
                parser_stage="stream_length.endstream_missing",
            ))
            continue
        # Distance from payload start to endstream keyword
        gap = es - payload_start
        # Declared length past end of object / file
        if payload_start + length > len(pdf_bytes):
            res.add(StructFinding(
                code="STREAM_LENGTH_BOUNDARY_CONTRADICTION",
                detail=(
                    f"obj {onum} {ogen}: /Length={length} exceeds file bounds "
                    f"from offset {payload_start}"
                ),
                object_number=onum,
                generation=ogen,
                offset=payload_start,
                expected=f"<= {len(pdf_bytes) - payload_start}",
                actual=str(length),
                parser_stage="stream_length.file_bounds",
            ))
            continue
        if payload_start + length > endobj:
            res.add(StructFinding(
                code="STREAM_LENGTH_BOUNDARY_CONTRADICTION",
                detail=(
                    f"obj {onum} {ogen}: /Length={length} extends past endobj"
                ),
                object_number=onum,
                generation=ogen,
                offset=payload_start,
                expected=f"<= {endobj - payload_start}",
                actual=str(length),
                parser_stage="stream_length.obj_bounds",
            ))
        # endstream falls inside declared payload → contradiction
        if es < payload_start + length:
            res.add(StructFinding(
                code="STREAM_ENDSTREAM_CONTRADICTION",
                detail=(
                    f"obj {onum} {ogen}: endstream at +{gap} lies inside "
                    f"declared /Length={length} (mode={mode}); refusing silent fallback"
                ),
                object_number=onum,
                generation=ogen,
                offset=payload_start,
                expected=f"endstream >= {length}",
                actual=str(gap),
                parser_stage="stream_length.endstream_inside",
            ))
        # Large mismatch vs actual endstream (beyond CRLF tolerance) when Length
        # is past endstream already covered; if Length much shorter than gap
        # without endstream inside — not necessarily a contradiction (padding
        # after payload before endstream is rare but not always forged).
        elif abs(gap - length) > 2 and length > gap:
            # length claims more bytes than available before endstream
            res.add(StructFinding(
                code="STREAM_ENDSTREAM_CONTRADICTION",
                detail=(
                    f"obj {onum} {ogen}: /Length={length} > bytes before "
                    f"endstream ({gap})"
                ),
                object_number=onum,
                generation=ogen,
                offset=payload_start,
                expected=str(gap),
                actual=str(length),
                parser_stage="stream_length.length_gt_gap",
            ))
    res.stats["streams_checked"] = checked
    return res
