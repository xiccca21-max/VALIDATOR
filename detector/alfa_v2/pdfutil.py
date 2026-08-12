"""Small defensive PDF helpers shared only by Alfa v2 forensic modules."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

_OBJ_RE = re.compile(rb"(?m)^\s*(\d+)\s+(\d+)\s+obj\b")


@dataclass(frozen=True)
class PdfObject:
    number: int
    generation: int
    offset: int
    body: bytes
    dictionary: bytes
    raw_stream: bytes | None
    decoded_stream: bytes | None


def objects(pdf: bytes) -> dict[int, PdfObject]:
    """Parse ordinary indirect objects; malformed/object-stream PDFs fail closed."""
    starts = list(_OBJ_RE.finditer(pdf))
    lengths = {
        int(m.group(1)): int(m.group(2))
        for m in re.finditer(rb"(?ms)^\s*(\d+)\s+0\s+obj\s+(\d+)\s+endobj", pdf)
    }
    out: dict[int, PdfObject] = {}
    for index, match in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(pdf)
        end = pdf.find(b"endobj", match.end(), stop)
        if end < 0:
            continue
        body = pdf[match.end():end]
        sm = re.search(rb"stream(?:\r\n|\n|\r)", body)
        dictionary = body[:sm.start()] if sm else body
        raw: bytes | None = None
        decoded: bytes | None = None
        if sm:
            begin = sm.end()
            direct = re.search(rb"/Length\s+(\d+)(?!\s+0\s+R)", dictionary)
            indirect = re.search(rb"/Length\s+(\d+)\s+0\s+R", dictionary)
            length = int(direct.group(1)) if direct else lengths.get(int(indirect.group(1))) if indirect else None
            if length is not None and 0 <= length <= len(body) - begin:
                raw = body[begin:begin + length]
            else:
                stream_end = body.find(b"endstream", begin)
                if stream_end >= 0:
                    raw = body[begin:stream_end].rstrip(b"\r\n")
            if raw is not None:
                if b"/FlateDecode" in dictionary:
                    try:
                        decoded = zlib.decompress(raw)
                    except zlib.error:
                        decoded = None
                elif b"/Filter" not in dictionary:
                    decoded = raw
        number = int(match.group(1))
        out[number] = PdfObject(
            number, int(match.group(2)), match.start(), body, dictionary, raw, decoded
        )
    return out


def refs(blob: bytes, key: bytes) -> list[int]:
    match = re.search(rb"/" + re.escape(key) + rb"\s*(\[(.*?)\]|(\d+)\s+0\s+R)", blob, re.S)
    if not match:
        return []
    return [int(value) for value in re.findall(rb"(\d+)\s+0\s+R", match.group(0))]


def resource_map(pdf: bytes, kind: bytes) -> dict[str, int]:
    pattern = rb"/" + re.escape(kind) + rb"\s*<<(.*?)>>"
    result: dict[str, int] = {}
    for section in re.finditer(pattern, pdf, re.S):
        for name, number in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", section.group(1)):
            result[name.decode("latin1")] = int(number)
    return result


def stream_role(obj: PdfObject) -> str:
    d, dec = obj.dictionary, obj.decoded_stream or b""
    if b"/Subtype" in d and b"/Image" in d:
        return "image"
    if b"/N " in d and (b"/Alternate" in d or b"/ColorSpace" in d):
        return "icc"
    if dec.startswith((b"\x00\x01\x00\x00", b"OTTO", b"ttcf")):
        return "font"
    if b"beginbfchar" in dec or b"beginbfrange" in dec:
        return "tounicode"
    if b"BT" in dec and (b"Tj" in dec or b"TJ" in dec):
        return "content"
    if b"/Type /XRef" in d:
        return "xref"
    return "other"
