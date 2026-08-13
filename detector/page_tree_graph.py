"""Page tree graph contradiction auditor."""

from __future__ import annotations

import re

from .structural_deep_xref_stream import (
    DeepAuditResult,
    StructFinding,
    index_indirect_objects,
)

_ROOT_RE = re.compile(rb"/Root\s+(\d+)\s+(\d+)\s+R")
_PAGES_RE = re.compile(rb"/Pages\s+(\d+)\s+(\d+)\s+R")
_TYPE_RE = re.compile(rb"/Type\s*/(\w+)")
_KIDS_RE = re.compile(rb"/Kids\s*\[(.*?)\]", re.S)
_PARENT_RE = re.compile(rb"/Parent\s+(\d+)\s+(\d+)\s+R")
_COUNT_RE = re.compile(rb"/Count\s+(\d+)")
_CONTENTS_RE = re.compile(rb"/Contents\s+(\d+)\s+(\d+)\s+R")
_CONTENTS_ARR_RE = re.compile(rb"/Contents\s*\[(.*?)\]", re.S)
_REF_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")
_OBJ_BODY_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)


def _obj_body(
    pdf_bytes: bytes,
    index: dict[tuple[int, int], int],
    num: int,
    gen: int = 0,
) -> bytes | None:
    key = (num, gen)
    if key not in index:
        # try any generation
        cands = [k for k in index if k[0] == num]
        if not cands:
            return None
        key = cands[0]
    start = index[key]
    end = pdf_bytes.find(b"endobj", start)
    if end < 0:
        return pdf_bytes[start : start + 50_000]
    return pdf_bytes[start : end + 6]


def _trailer_root(pdf_bytes: bytes) -> tuple[int, int] | None:
    # Prefer last trailer
    last = None
    for m in re.finditer(rb"trailer\s*<<", pdf_bytes):
        chunk = pdf_bytes[m.start() : m.start() + 800]
        rm = _ROOT_RE.search(chunk)
        if rm:
            last = (int(rm.group(1)), int(rm.group(2)))
    if last:
        return last
    # xref stream
    sx = pdf_bytes.rfind(b"startxref")
    if sx >= 0:
        sm = re.search(rb"startxref\s+(\d+)", pdf_bytes[sx : sx + 64])
        if sm:
            off = int(sm.group(1))
            head = pdf_bytes[off : off + 1200]
            rm = _ROOT_RE.search(head)
            if rm:
                return int(rm.group(1)), int(rm.group(2))
    return None


def audit_page_tree(pdf_bytes: bytes) -> DeepAuditResult:
    res = DeepAuditResult()
    index = index_indirect_objects(pdf_bytes)
    root = _trailer_root(pdf_bytes)
    if not root:
        res.stats["pagetree"] = "no_root"
        return res
    rnum, rgen = root
    catalog = _obj_body(pdf_bytes, index, rnum, rgen)
    if catalog is None:
        res.add(StructFinding(
            code="CRITICAL_INDIRECT_REFERENCE_BROKEN",
            detail=f"/Root {rnum} {rgen} R missing",
            object_number=rnum,
            generation=rgen,
            parser_stage="pagetree.root",
        ))
        return res

    pm = _PAGES_RE.search(catalog)
    if not pm:
        # Catalog might itself be Pages in broken files
        if b"/Type /Pages" in catalog or b"/Type/Pages" in catalog:
            pages_num, pages_gen = rnum, rgen
        else:
            res.stats["pagetree"] = "no_pages_key"
            return res
    else:
        pages_num, pages_gen = int(pm.group(1)), int(pm.group(2))

    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int, int | None]] = [(pages_num, pages_gen, None)]
    page_nodes = 0
    declared_counts: list[tuple[int, int, int, int]] = []  # num,gen,count,kids

    while stack:
        num, gen, parent = stack.pop()
        key = (num, gen)
        if key in visited:
            res.add(StructFinding(
                code="PAGETREE_CYCLE",
                detail=f"cycle involving Pages/Page node {num} {gen}",
                object_number=num,
                generation=gen,
                parser_stage="pagetree.cycle",
            ))
            continue
        visited.add(key)
        body = _obj_body(pdf_bytes, index, num, gen)
        if body is None:
            res.add(StructFinding(
                code="CRITICAL_INDIRECT_REFERENCE_BROKEN",
                detail=f"page tree node {num} {gen} R missing",
                object_number=num,
                generation=gen,
                parser_stage="pagetree.missing_node",
            ))
            continue

        # Parent consistency
        par = _PARENT_RE.search(body)
        if parent is not None:
            if not par:
                res.add(StructFinding(
                    code="PAGETREE_PARENT_CONTRADICTION",
                    detail=f"node {num} missing /Parent (expected {parent})",
                    object_number=num,
                    generation=gen,
                    expected=str(parent),
                    actual="missing",
                    parser_stage="pagetree.parent_missing",
                ))
            else:
                pnum = int(par.group(1))
                if pnum != parent:
                    res.add(StructFinding(
                        code="PAGETREE_PARENT_CONTRADICTION",
                        detail=(
                            f"node {num} /Parent={pnum} but reachable from {parent}"
                        ),
                        object_number=num,
                        generation=gen,
                        expected=str(parent),
                        actual=str(pnum),
                        parser_stage="pagetree.parent",
                    ))

        typ_m = _TYPE_RE.search(body)
        typ = typ_m.group(1).decode() if typ_m else ""

        if typ == "Page" or (b"/Contents" in body and typ != "Pages"):
            page_nodes += 1
            # Contents refs
            crefs: list[tuple[int, int]] = []
            cm = _CONTENTS_RE.search(body)
            if cm:
                crefs.append((int(cm.group(1)), int(cm.group(2))))
            ca = _CONTENTS_ARR_RE.search(body)
            if ca:
                for rm in _REF_RE.finditer(ca.group(1)):
                    crefs.append((int(rm.group(1)), int(rm.group(2))))
            for cn, cg in crefs:
                cbody = _obj_body(pdf_bytes, index, cn, cg)
                if cbody is None:
                    res.add(StructFinding(
                        code="PAGE_CONTENT_REFERENCE_INVALID",
                        detail=(
                            f"Page {num} /Contents {cn} {cg} R does not exist"
                        ),
                        object_number=num,
                        generation=gen,
                        expected=f"{cn} {cg} R",
                        actual="missing",
                        parser_stage="pagetree.contents",
                    ))
                    continue
                if b"stream" not in cbody and b"/Length" not in cbody:
                    # Contents may be an array object — allow if array of refs
                    if not re.search(rb"\[\s*\d+\s+\d+\s+R", cbody):
                        res.add(StructFinding(
                            code="PAGE_CONTENT_REFERENCE_INVALID",
                            detail=(
                                f"Page {num} /Contents {cn} {cg} R is not a "
                                f"stream or contents array"
                            ),
                            object_number=num,
                            generation=gen,
                            parser_stage="pagetree.contents_type",
                        ))
            continue

        # Pages node
        km = _KIDS_RE.search(body)
        kids: list[tuple[int, int]] = []
        if km:
            for rm in _REF_RE.finditer(km.group(1)):
                kids.append((int(rm.group(1)), int(rm.group(2))))
        cm = _COUNT_RE.search(body)
        if cm:
            declared_counts.append((num, gen, int(cm.group(1)), len(kids)))
        for kn, kg in kids:
            # existence
            if _obj_body(pdf_bytes, index, kn, kg) is None:
                res.add(StructFinding(
                    code="CRITICAL_INDIRECT_REFERENCE_BROKEN",
                    detail=f"/Kids ref {kn} {kg} R missing under {num}",
                    object_number=kn,
                    generation=kg,
                    parser_stage="pagetree.kids",
                ))
                continue
            stack.append((kn, kg, num))

    # Count vs reachable pages — only for root pages node when kids are all pages
    for num, gen, count, kid_n in declared_counts:
        # If this node declares Count and we can count descendant pages from a
        # fresh walk — approximate: when kids length is 1 and Count absurdly larger
        body = _obj_body(pdf_bytes, index, num, gen) or b""
        km = _KIDS_RE.search(body)
        if not km:
            continue
        kids = [(int(a), int(b)) for a, b in _REF_RE.findall(km.group(1))]
        # Direct pages among kids
        direct_pages = 0
        for kn, kg in kids:
            kb = _obj_body(pdf_bytes, index, kn, kg) or b""
            kt = _TYPE_RE.search(kb)
            if kt and kt.group(1) == b"Page":
                direct_pages += 1
            elif b"/Contents" in kb and not (kt and kt.group(1) == b"Pages"):
                direct_pages += 1
        # If all kids are pages, Count must equal len(kids)
        if kids and direct_pages == len(kids) and count != len(kids):
            res.add(StructFinding(
                code="PAGETREE_COUNT_CONTRADICTION",
                detail=(
                    f"Pages {num} /Count={count} but {len(kids)} direct page kids"
                ),
                object_number=num,
                generation=gen,
                expected=str(len(kids)),
                actual=str(count),
                parser_stage="pagetree.count",
            ))

    res.stats["pagetree_nodes"] = len(visited)
    res.stats["page_nodes"] = page_nodes
    return res
