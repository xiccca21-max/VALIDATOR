"""Regression tests for structural_deep HARD checks.

Positive: one surgical contradiction → expected code.
Negative: valid minimal PDF → no findings for that code family.
"""

from __future__ import annotations

import re
import struct
import zlib

from detector.dict_key_conflict import audit_duplicate_critical_dict_keys
from detector.page_tree_graph import audit_page_tree
from detector.sfnt_math_integrity import audit_sfnt_math
from detector.structural_deep import run_structural_deep_audit
from detector.structural_deep_xref_stream import (
    ENABLED_STRUCTURAL_HARD,
    audit_stream_length_contract,
    audit_xref_deep,
)
from detector.tbank_sfnt_table_integrity import parse_sfnt_directory


def _build_minimal_pdf() -> bytes:
    """Tiny classic-xref PDF with consistent object numbers/offsets."""
    parts: list[bytes] = []
    parts.append(b"%PDF-1.4\n")
    objs = {
        1: b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        2: b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        3: (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R >>endobj\n"
        ),
        4: (
            b"4 0 obj<< /Length 33 >>stream\n"
            b"BT /F1 12 Tf 10 10 Td (Hi) Tj ET\n"
            b"endstream\nendobj\n"
        ),
    }
    offsets = {0: 0}
    body = bytearray(parts[0])
    for n in range(1, 5):
        offsets[n] = len(body)
        body += objs[n]
    xref_pos = len(body)
    xref = bytearray(b"xref\n0 5\n")
    xref += b"0000000000 65535 f \n"
    for n in range(1, 5):
        xref += f"{offsets[n]:010d} 00000 n \n".encode()
    trailer = (
        b"trailer<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(body + xref + trailer)


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_negative_valid_minimal_clean():
    pdf = _build_minimal_pdf()
    res = run_structural_deep_audit(pdf)
    # Valid PDF may still emit SFNT nothing; xref/stream/pagetree must be clean
    bad = _codes(res.findings) & {
        "XREF_ENTRY_OBJECT_MISMATCH",
        "XREF_GENERATION_MISMATCH",
        "XREF_SUBSECTION_INVALID",
        "XREF_SIZE_CONTRADICTION",
        "XREF_DUPLICATE_LIVE_MAPPING",
        "STREAM_LENGTH_BOUNDARY_CONTRADICTION",
        "STREAM_ENDSTREAM_CONTRADICTION",
        "PAGETREE_CYCLE",
        "PAGETREE_COUNT_CONTRADICTION",
        "PAGETREE_PARENT_CONTRADICTION",
        "PAGE_CONTENT_REFERENCE_INVALID",
        "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT",
    }
    assert not bad, bad


def test_xref_object_number_mismatch():
    pdf = _build_minimal_pdf()
    # Point object 3's xref entry at object 4's offset (neighbor)
    # Find xref line for obj 3 (4th live after free)
    m = re.search(rb"xref\n0 5\n(?:[^\n]+\n){3}(\d{10}) 00000 n ", pdf)
    assert m
    # offsets: free,1,2,3,4 — group above is entry index 3? 
    # lines after 0 5: [0]=free [1]=obj1 [2]=obj2 [3]=obj3 [4]=obj4
    # Capture for obj3 is (?:){3} from start of entries = free+1+2 → next is obj3
    obj4_off = int(re.search(rb"(?m)^4 0 obj", pdf).start())
    # Replace obj3 entry offset with obj4 offset
    entries = list(re.finditer(rb"(\d{10}) 00000 n ", pdf))
    assert len(entries) >= 4
    e3 = entries[2]  # obj 3 is third live (1-index: entries[0]=obj1)
    # entries[0]=obj1, [1]=obj2, [2]=obj3, [3]=obj4
    new = pdf[: e3.start(1)] + f"{obj4_off:010d}".encode() + pdf[e3.end(1) :]
    res = audit_xref_deep(new)
    assert "XREF_ENTRY_OBJECT_MISMATCH" in _codes(res.findings), [f.detail for f in res.findings]


def test_xref_generation_mismatch():
    pdf = _build_minimal_pdf()
    entries = list(re.finditer(rb"(\d{10}) (\d{5}) n ", pdf))
    e = entries[0]  # obj1
    new = pdf[: e.start(2)] + b"00001" + pdf[e.end(2) :]
    res = audit_xref_deep(new)
    assert "XREF_GENERATION_MISMATCH" in _codes(res.findings)


def test_stream_length_endstream_inside_payload():
    pdf = _build_minimal_pdf()
    # Inflate /Length beyond endstream
    new = pdf.replace(b"/Length 33", b"/Length 80")
    res = audit_stream_length_contract(new)
    assert "STREAM_ENDSTREAM_CONTRADICTION" in _codes(res.findings)


def test_duplicate_contents_conflict():
    pdf = _build_minimal_pdf()
    old = b"/Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R"
    new_dict = (
        b"/Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Contents 2 0 R"
    )
    new = pdf.replace(old, new_dict)
    # Offsets break xref — rebuild not required for dict auditor (byte scan)
    res = audit_duplicate_critical_dict_keys(new)
    assert "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT" in _codes(res.findings)


def test_pagetree_count_contradiction():
    pdf = _build_minimal_pdf()
    new = pdf.replace(b"/Kids [3 0 R] /Count 1", b"/Kids [3 0 R] /Count 9")
    res = audit_page_tree(new)
    assert "PAGETREE_COUNT_CONTRADICTION" in _codes(res.findings)


def test_pagetree_bad_contents_ref():
    pdf = _build_minimal_pdf()
    new = pdf.replace(b"/Contents 4 0 R", b"/Contents 99 0 R")
    res = audit_page_tree(new)
    assert "PAGE_CONTENT_REFERENCE_INVALID" in _codes(res.findings)


def _tiny_ttf() -> bytes:
    """Minimal SFNT with one empty 'head'-like table for checksum tests."""
    # Build 1-table font: only 'head' with 54 zero bytes (enough for loca format field)
    head = bytearray(54)
    tables = [(b"head", bytes(head))]
    num = len(tables)
    search_range = 16
    entry_selector = 0
    range_shift = num * 16 - search_range
    offset = 12 + num * 16
    records = []
    payload = b""
    for tag, data in tables:
        # pad to 4
        pad = (4 - (len(data) % 4)) % 4
        data_p = data + b"\x00" * pad
        # checksum
        csum = 0
        tmp = bytearray(data_p)
        if tag == b"head" and len(tmp) >= 12:
            tmp[8:12] = b"\x00\x00\x00\x00"
        for i in range(0, len(tmp), 4):
            csum = (csum + struct.unpack(">I", bytes(tmp[i : i + 4]))[0]) & 0xFFFFFFFF
        records.append((tag, csum, offset + len(payload), len(data)))
        payload += data_p
    hdr = struct.pack(
        ">IHHHH",
        0x00010000,
        num,
        search_range,
        entry_selector,
        range_shift,
    )
    directory = b"".join(
        struct.pack(">4sIII", tag, csum, off, length)
        for tag, csum, off, length in records
    )
    return hdr + directory + payload


def test_sfnt_directory_overlap_or_checksum():
    ttf = bytearray(_tiny_ttf())
    # Corrupt directory checksum field for head
    # header 12 + tag(4) = checksum at offset 16
    ttf[16:20] = b"\xDE\xAD\xBE\xEF"
    # Embed in PDF FontFile2 stream
    raw = zlib.compress(bytes(ttf))
    pdf = _build_minimal_pdf()
    # Append a fontfile object (won't fix xref — auditor scans FontFile2 refs OR magic)
    # Inject stream with SFNT via Flate into a new object blob appended before xref
    # Simpler: call parse + checksum path via embedding /FontFile2
    font_obj = (
        b"9 0 obj<< /Length "
        + str(len(raw)).encode()
        + b" /Filter /FlateDecode /Length1 "
        + str(len(ttf)).encode()
        + b" >>stream\n"
        + raw
        + b"\nendstream\nendobj\n"
    )
    # Put FontFile2 reference + object into page resources area by appending before xref
    xref = pdf.find(b"xref\n")
    inject = b"/FontFile2 9 0 R\n" + font_obj
    new = pdf[:xref] + inject + pdf[xref:]
    res = audit_sfnt_math(new)
    assert _codes(res.findings) & {
        "SFNT_TABLE_CHECKSUM_INVALID",
        "SFNT_DIRECTORY_CONTRADICTION",
        "SFNT_CHECKSUM_ADJUSTMENT_INVALID",
    }, [f.detail for f in res.findings]


def test_enabled_gate_defaults_empty():
    """Enabled set is corpus-gated; STREAM_* is enabled only at 0 FP.

    If a code is not in ENABLED_STRUCTURAL_HARD it must stay diagnostic.
    """
    assert isinstance(ENABLED_STRUCTURAL_HARD, frozenset)
    pdf = _build_minimal_pdf()
    # force a mismatch
    new = pdf.replace(b"/Length 33", b"/Length 80")
    res = run_structural_deep_audit(new)
    code = "STREAM_ENDSTREAM_CONTRADICTION"
    if code not in ENABLED_STRUCTURAL_HARD:
        assert not any(f.code == code for f in res.hard_findings)
        assert any(f.code == code for f in res.diagnostic_findings)
    else:
        assert any(f.code == code for f in res.hard_findings)


def test_route_smoke_on_minimal():
    from detector import route

    bank, result, _ = route(_build_minimal_pdf())
    assert result.get("verdict") in (
        "ЧИСТО",
        "ФЕЙК",
        "НЕИЗВЕСТНЫЙ ДОКУМЕНТ",
        "ОРИГИНАЛ",
    )
