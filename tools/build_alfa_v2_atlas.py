#!/usr/bin/env python3
"""Build the versioned Alfa v2 forensic atlas from the fixed 40-PDF corpus.

The output is observational data. In particular, hashes of compressed PDF
streams are retained for provenance diagnostics and are never authenticity
contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
OUT_DIR = ROOT / "detector" / "alfa_v2" / "atlas_data"

SCHEMA = "alfa-v2-atlas"
VERSION = "1.0.0"
EXPECTED = {
    "pdf_count": 40,
    "methods": {"sbp": 37, "card": 2, "phone": 1},
    "emitters": {"oracle_bi": 14, "ios_quartz": 26},
    "pdf_versions": {"1.6": 14, "1.3": 26},
}
ARTIFACTS = {
    "manifest": "manifest.v1.json",
    "profiles": "profiles.v1.json",
    "streams_images": "streams-images.v1.json",
    "sbp": "sbp-segmentation.v1.json",
    "fields": "field-orders.v1.json",
    "fonts": "font-inventory.v1.json",
    "glyphs": "glyph-geometry.v1.json",
    "index": "index.v1.json",
}

_OBJ_REF_RE = re.compile(r"(\d+)\s+0\s+R")
_PDF_VERSION_RE = re.compile(rb"%PDF-(\d\.\d)")
_SBP_RE = re.compile(r"[AB][0-9A-Z]{31}")
_OP_RE = re.compile(r"(?:C|Z)\d{15}")
_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}")
_HEX_TJ_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>")
_FILTER_RE = re.compile(r"/Filter\s*(?:\[\s*)?/([A-Za-z0-9]+)")
_ALFA_CARD_BINS = {
    "220015",
    "220220",
    "415481",
    "437772",
    "458410",
    "479087",
    "521178",
    "548601",
    "548655",
    "552175",
    "555949",
    "676230",
}
_FIELD_LABELS = (
    "сформирована",
    "квитанция о переводе по сбп",
    "квитанция о переводе с карты на карту",
    "квитанция о переводе клиенту альфа-банка",
    "сумма перевода",
    "комиссия",
    "списано с учётом комиссии",
    "дата и время перевода",
    "дата и время операции",
    "номер операции",
    "получатель",
    "телефон получателя",
    "номер телефона получателя",
    "банк получателя",
    "счёт получателя",
    "счет получателя",
    "идентификатор операции в сбп",
    "идентификатор операции сбп",
    "номер карты отправителя",
    "номер карты получателя",
    "отправитель",
    "сообщение получателю",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any, *, pretty: bool = False) -> bytes:
    kwargs: dict[str, Any] = {
        "ensure_ascii": False,
        "sort_keys": True,
    }
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    return (json.dumps(value, **kwargs) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _write_artifact(name: str, value: Any, *, immutable: bool = False) -> Path:
    path = OUT_DIR / ARTIFACTS[name]
    data = _canonical_bytes(value, pretty=name in {"manifest", "index"})
    if immutable and path.exists():
        old = path.read_bytes()
        if old != data:
            raise RuntimeError(
                f"immutable manifest differs: {path}; use a new manifest version"
            )
        return path
    _atomic_write(path, data)
    return path


def _pdf_text(doc: fitz.Document) -> str:
    return "\n".join(page.get_text("text") for page in doc)


def _norm_line(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").replace("ё", "е").split()).strip().lower()


def _classify(text: str, producer: str) -> tuple[str, str, str]:
    low = _norm_line(text)
    emitter = "ios_quartz" if "quartz pdfcontext" in producer.lower() else "oracle_bi"
    if "квитанция о переводе по сбп" in low:
        return emitter, "sbp", "sbp"
    if "квитанция о переводе с карты на карту" in low:
        recipient = low.split("банк получателя", 1)[-1][:100]
        raw = text.replace("\xa0", " ")
        card_tail = raw.lower().split("номер карты получателя", 1)[-1][:160]
        card_match = re.search(r"(\d{6})\*+\d{4}", card_tail)
        is_alfa = "альфа" in recipient or (
            card_match is not None and card_match.group(1) in _ALFA_CARD_BINS
        )
        subtype = "card_intrabank" if is_alfa else "card_interbank"
        return emitter, "card", subtype
    return emitter, "phone", "intrabank_phone"


def _xref_ref(doc: fitz.Document, xref: int, key: str) -> int | None:
    kind, value = doc.xref_get_key(xref, key)
    if kind == "xref":
        return int(value.split()[0])
    if kind in {"array", "dict"}:
        m = _OBJ_REF_RE.search(value)
        return int(m.group(1)) if m else None
    return None


def _resolve_stream_ref(doc: fitz.Document, xref: int, key: str) -> int | None:
    ref = _xref_ref(doc, xref, key)
    if ref and doc.xref_is_stream(ref):
        return ref
    return ref


def _font_refs(doc: fitz.Document, font_xref: int) -> dict[str, int]:
    refs: dict[str, int] = {"font": font_xref}
    desc = _xref_ref(doc, font_xref, "DescendantFonts")
    if desc:
        refs["descendant"] = desc
        width = _xref_ref(doc, desc, "W")
        if width:
            refs["widths"] = width
        descriptor = _xref_ref(doc, desc, "FontDescriptor")
        if descriptor:
            refs["descriptor"] = descriptor
            fontfile = _xref_ref(doc, descriptor, "FontFile2")
            if fontfile:
                refs["fontfile2"] = fontfile
    tounicode = _xref_ref(doc, font_xref, "ToUnicode")
    if tounicode:
        refs["tounicode"] = tounicode
    cidmap = _xref_ref(doc, desc, "CIDToGIDMap") if desc else None
    if cidmap:
        refs["cid_to_gid"] = cidmap
    return refs


def _icc_ref(doc: fitz.Document, image_xref: int) -> int | None:
    seen: set[int] = set()
    pending = [image_xref]
    while pending:
        xref = pending.pop()
        if xref in seen:
            continue
        seen.add(xref)
        obj = doc.xref_object(xref)
        if "/ICCBased" in obj:
            tail = obj.split("/ICCBased", 1)[1]
            m = _OBJ_REF_RE.search(tail)
            if m:
                return int(m.group(1))
        for m in _OBJ_REF_RE.finditer(obj):
            child = int(m.group(1))
            if child not in seen:
                pending.append(child)
    return None


def _stream_filter(doc: fitz.Document, xref: int) -> list[str]:
    obj = doc.xref_object(xref)
    return _FILTER_RE.findall(obj)


def _used_cids(content: bytes) -> set[int]:
    used: set[int] = set()
    for match in _HEX_TJ_RE.finditer(content):
        compact = re.sub(rb"\s+", b"", match.group(1))
        if len(compact) % 4:
            continue
        try:
            raw = bytes.fromhex(compact.decode("ascii"))
        except ValueError:
            continue
        for pos in range(0, len(raw), 2):
            if pos + 2 <= len(raw):
                used.add(int.from_bytes(raw[pos : pos + 2], "big"))
    return used


def _parse_tounicode(data: bytes) -> dict[int, str]:
    text = data.decode("latin1", "ignore")
    out: dict[int, str] = {}

    def decode_unicode(hex_value: str) -> str:
        raw = bytes.fromhex(hex_value)
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", text):
        if len(src) <= 4:
            value = decode_unicode(dst)
            if value:
                out[int(src, 16)] = value
    for start, end, dst in re.findall(
        r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
        text,
    ):
        a, b, base = int(start, 16), int(end, 16), int(dst, 16)
        width = len(dst)
        for offset, cid in enumerate(range(a, b + 1)):
            value = decode_unicode(f"{base + offset:0{width}X}")
            if value:
                out[cid] = value
    return out


def _balanced_array(value: str, start: int) -> str:
    depth = 0
    for pos in range(start, len(value)):
        if value[pos] == "[":
            depth += 1
        elif value[pos] == "]":
            depth -= 1
            if depth == 0:
                return value[start : pos + 1]
    return ""


def _parse_widths(value: str) -> tuple[int, dict[int, int], str]:
    dw_match = re.search(r"/DW\s+(-?\d+)", value)
    default = int(dw_match.group(1)) if dw_match else 1000
    marker = re.search(r"/W\s+", value)
    if not marker:
        return default, {}, ""
    start = value.find("[", marker.end())
    array = _balanced_array(value, start) if start >= 0 else ""
    widths: dict[int, int] = {}
    for match in re.finditer(r"(\d+)\s*\[([^\]]*)\]", array):
        first = int(match.group(1))
        nums = [int(x) for x in re.findall(r"-?\d+", match.group(2))]
        for offset, width in enumerate(nums):
            widths[first + offset] = width
    residual = re.sub(r"\d+\s*\[[^\]]*\]", " ", array)
    for match in re.finditer(r"(\d+)\s+(\d+)\s+(-?\d+)", residual):
        first, last, width = map(int, match.groups())
        for cid in range(first, last + 1):
            widths[cid] = width
    return default, widths, array


def _font_program(doc: fitz.Document, refs: dict[str, int]) -> bytes:
    xref = refs.get("fontfile2")
    return (doc.xref_stream(xref) or b"") if xref else b""


def _cid_to_gid(doc: fitz.Document, refs: dict[str, int], cid: int) -> int:
    xref = refs.get("cid_to_gid")
    if not xref:
        return cid
    data = doc.xref_stream(xref) or b""
    pos = cid * 2
    return int.from_bytes(data[pos : pos + 2], "big") if pos + 2 <= len(data) else 0


def _table_inventory(tt: TTFont) -> list[dict[str, Any]]:
    result = []
    for tag in sorted(tt.reader.keys()):
        data = tt.getTableData(tag)
        result.append({"tag": tag, "length": len(data), "sha256": _sha(data)})
    return result


def _canonical_geometry(tt: TTFont, gid: int) -> tuple[str, dict[str, Any]] | None:
    order = tt.getGlyphOrder()
    if gid < 0 or gid >= len(order):
        return None
    glyph_set = tt.getGlyphSet()
    glyph_name = order[gid]
    pen = DecomposingRecordingPen(glyph_set)
    try:
        glyph_set[glyph_name].draw(pen)
    except Exception:
        return None
    upem = int(tt["head"].unitsPerEm)
    commands: list[list[Any]] = []
    point_count = 0
    for operator, operands in pen.value:
        normalized = []
        for operand in operands:
            if isinstance(operand, tuple):
                normalized.append([round(float(v) / upem, 6) for v in operand])
                point_count += 1
            else:
                normalized.append(operand)
        commands.append([operator, normalized])
    payload = _canonical_bytes(commands)
    geometry_hash = _sha(payload)
    glyph = tt["glyf"][glyph_name]
    try:
        glyph.recalcBounds(tt["glyf"])
        bbox = [
            round(float(glyph.xMin) / upem, 6),
            round(float(glyph.yMin) / upem, 6),
            round(float(glyph.xMax) / upem, 6),
            round(float(glyph.yMax) / upem, 6),
        ]
    except Exception:
        bbox = [0.0, 0.0, 0.0, 0.0]
    return geometry_hash, {
        "commands": commands,
        "bbox_em": bbox,
        "contours": sum(1 for command, _ in pen.value if command == "closePath"),
        "points": point_count,
    }


def _field_order(text: str) -> list[str]:
    ordered: list[str] = []
    for raw in text.splitlines():
        line = _norm_line(raw)
        if not line:
            continue
        match = next((label for label in _FIELD_LABELS if line == label), None)
        if match and (not ordered or ordered[-1] != match):
            ordered.append(match)
    return ordered


def _sbp_tuple(sbp_id: str, operation_id: str, operation_date: str) -> dict[str, Any]:
    encoded_day = int(sbp_id[1:5]) % 1000
    date_match = _DATE_RE.search(operation_date)
    observed_day = None
    if date_match:
        from datetime import datetime

        observed_day = datetime.strptime(
            date_match.group(0), "%d.%m.%Y %H:%M:%S"
        ).timetuple().tm_yday
    return {
        "operation_id": operation_id,
        "sbp_id": sbp_id,
        "segments": {
            "operation_type": sbp_id[0],
            "year_day": sbp_id[1:5],
            "hour_utc": sbp_id[5:7],
            "minute": sbp_id[7:9],
            "second": sbp_id[9:11],
            "reference": sbp_id[11:17],
            "separator": sbp_id[17],
            "channel": sbp_id[18:22],
            "emitter_core": sbp_id[22:27],
            "route_tail": sbp_id[27:32],
        },
        "empirical": {
            "operation_datetime": date_match.group(0) if date_match else "",
            "encoded_day_of_year": encoded_day,
            "observed_day_of_year": observed_day,
            "day_delta": encoded_day - observed_day if observed_day else None,
            "reference_letter_count": sum(ch.isalpha() for ch in sbp_id[11:17]),
            "reference_terminal_zero": sbp_id[16] == "0",
        },
    }


def _profile_contracts(samples: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        groups[(sample["emitter"], sample["method"], sample["submethod"])].append(sample)
    contracts = []
    for (emitter, method, submethod), rows in sorted(groups.items()):
        contracts.append(
            {
                "profile_id": f"{emitter}:{method}:{submethod}",
                "emitter": emitter,
                "method": method,
                "submethod": submethod,
                "sample_count": len(rows),
                "producer_values": sorted({row["producer"] for row in rows}),
                "pdf_versions": sorted({row["pdf_version"] for row in rows}),
                "page_counts": sorted({row["page_count"] for row in rows}),
                "object_count_observed": {
                    "min": min(row["object_count"] for row in rows),
                    "max": max(row["object_count"] for row in rows),
                    "values": sorted({row["object_count"] for row in rows}),
                },
                "resource_fonts": sorted({font for row in rows for font in row["font_resources"]}),
                "image_dimensions": sorted(
                    {tuple(dim) for row in rows for dim in row["image_dimensions"]}
                ),
                "contract_semantics": "closed observations for emitter/submethod routing by Alfa v2",
            }
        )
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "contracts": contracts,
    }


def build() -> dict[str, Any]:
    pdfs = sorted(CORPUS.glob("*.pdf"), key=lambda p: p.name.casefold())
    if len(pdfs) != EXPECTED["pdf_count"]:
        raise RuntimeError(f"expected 40 PDFs, found {len(pdfs)} in {CORPUS}")

    samples: list[dict[str, Any]] = []
    streams_by_file: list[dict[str, Any]] = []
    images_by_file: list[dict[str, Any]] = []
    fonts_by_file: list[dict[str, Any]] = []
    sbp_entries: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    geometries: dict[str, dict[str, Any]] = {}
    glyph_observations: list[dict[str, Any]] = []
    manifest_files: list[dict[str, Any]] = []

    for path in pdfs:
        pdf = path.read_bytes()
        file_sha = _sha(pdf)
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = _pdf_text(doc)
        metadata = doc.metadata or {}
        producer = metadata.get("producer") or ""
        emitter, method, submethod = _classify(text, producer)
        version_match = _PDF_VERSION_RE.match(pdf)
        pdf_version = version_match.group(1).decode("ascii") if version_match else ""
        page = doc[0]
        page_fonts = page.get_fonts(full=True)
        page_images = page.get_images(full=True)
        content_xrefs = set(page.get_contents())
        image_xrefs = {entry[0] for entry in page_images}
        role_by_xref: dict[int, set[str]] = defaultdict(set)
        for xref in content_xrefs:
            role_by_xref[xref].add("page_content")
        for xref in image_xrefs:
            role_by_xref[xref].add("static_image")

        all_font_refs: dict[str, dict[str, int]] = {}
        for entry in page_fonts:
            resource = entry[4]
            refs = _font_refs(doc, entry[0])
            all_font_refs[resource] = refs
            for role, xref in refs.items():
                role_by_xref[xref].add(f"font_{role}")

        image_records = []
        for entry in page_images:
            xref, width, height = entry[0], entry[2], entry[3]
            decoded = doc.xref_stream(xref) or b""
            raw = doc.xref_stream_raw(xref) or b""
            icc_xref = _icc_ref(doc, xref)
            icc_decoded = (doc.xref_stream(icc_xref) or b"") if icc_xref else b""
            if icc_xref:
                role_by_xref[icc_xref].add("icc_profile")
            image_records.append(
                {
                    "xref": xref,
                    "width": width,
                    "height": height,
                    "colorspace": entry[5],
                    "decoded_sha256": _sha(decoded),
                    "decoded_length": len(decoded),
                    "icc_sha256": _sha(icc_decoded) if icc_decoded else None,
                    "icc_length": len(icc_decoded),
                    "compressed_sha256_provenance_only": _sha(raw),
                }
            )
        images_by_file.append({"file_sha256": file_sha, "images": image_records})

        stream_records = []
        for xref in range(1, doc.xref_length()):
            if not doc.xref_is_stream(xref):
                continue
            raw = doc.xref_stream_raw(xref) or b""
            decoded = doc.xref_stream(xref) or b""
            stream_records.append(
                {
                    "xref": xref,
                    "roles": sorted(role_by_xref.get(xref) or {"unclassified"}),
                    "filters": _stream_filter(doc, xref),
                    "raw_length": len(raw),
                    "decoded_length": len(decoded),
                    "compressed_sha256_provenance_only": _sha(raw),
                    "decoded_sha256": _sha(decoded),
                }
            )
        streams_by_file.append({"file_sha256": file_sha, "streams": stream_records})

        content = b"\n".join(doc.xref_stream(xref) or b"" for xref in content_xrefs)
        used_cids = _used_cids(content)
        file_font_records = []
        for entry in page_fonts:
            font_xref, extension, subtype, basefont, resource, encoding = entry[:6]
            refs = all_font_refs[resource]
            descendant = refs.get("descendant")
            desc_obj = doc.xref_object(descendant) if descendant else ""
            width_ref = refs.get("widths")
            if width_ref and doc.xref_is_stream(width_ref):
                width_source = (doc.xref_stream(width_ref) or b"").decode("latin1", "ignore")
            elif width_ref:
                width_source = doc.xref_object(width_ref)
            else:
                width_source = desc_obj
            default_width, widths, width_raw = _parse_widths(width_source)
            tounicode_ref = refs.get("tounicode")
            tounicode_data = (
                doc.xref_stream(tounicode_ref) or b"" if tounicode_ref else b""
            )
            cmap = _parse_tounicode(tounicode_data)
            ttf_data = _font_program(doc, refs)
            tt = TTFont(BytesIO(ttf_data), lazy=False) if ttf_data else None
            tables = _table_inventory(tt) if tt else []
            mappings = []
            for cid in sorted(used_cids):
                gid = _cid_to_gid(doc, refs, cid)
                unicode_value = cmap.get(cid, "")
                geometry_hash = None
                if tt:
                    geometry = _canonical_geometry(tt, gid)
                    if geometry:
                        geometry_hash, detail = geometry
                        existing = geometries.setdefault(
                            geometry_hash,
                            {
                                "sha256": geometry_hash,
                                **detail,
                                "unicodes": [],
                                "resources": [],
                            },
                        )
                        for char in unicode_value:
                            codepoint = f"U+{ord(char):04X}"
                            if codepoint not in existing["unicodes"]:
                                existing["unicodes"].append(codepoint)
                        if resource not in existing["resources"]:
                            existing["resources"].append(resource)
                mappings.append(
                    {
                        "cid": cid,
                        "gid": gid,
                        "unicode": unicode_value,
                        "width": widths.get(cid, default_width),
                        "geometry_sha256": geometry_hash,
                    }
                )
                glyph_observations.append(
                    {
                        "file_sha256": file_sha,
                        "resource": resource,
                        "cid": cid,
                        "unicode": unicode_value,
                        "geometry_sha256": geometry_hash,
                    }
                )
            file_font_records.append(
                {
                    "resource": resource,
                    "xref": font_xref,
                    "extension": extension,
                    "subtype": subtype,
                    "basefont": basefont,
                    "family_contract": "Tahoma-like",
                    "encoding": encoding,
                    "refs": refs,
                    "used_cids": sorted(used_cids),
                    "used_mappings": mappings,
                    "default_width": default_width,
                    "w_array_sha256": _sha(width_raw.encode("latin1")) if width_raw else None,
                    "tounicode_sha256": _sha(tounicode_data) if tounicode_data else None,
                    "fontfile2_sha256": _sha(ttf_data) if ttf_data else None,
                    "tables": tables,
                }
            )
            if tt:
                tt.close()
        fonts_by_file.append({"file_sha256": file_sha, "fonts": file_font_records})

        flat = re.sub(r"\s+", "", text)
        sbp_match = _SBP_RE.search(flat)
        op_match = _OP_RE.search(flat)
        dates = _DATE_RE.findall(text.replace("\xa0", " "))
        if method == "sbp":
            if not sbp_match or not op_match:
                raise RuntimeError(f"missing SBP tuple in {path.name}")
            sbp_entry = _sbp_tuple(
                sbp_match.group(0),
                op_match.group(0),
                dates[-1] if dates else "",
            )
            sbp_entry["file_sha256"] = file_sha
            sbp_entries.append(sbp_entry)

        order = _field_order(text)
        order_sha = _sha("\n".join(order).encode("utf-8"))
        field_rows.append(
            {
                "file_sha256": file_sha,
                "emitter": emitter,
                "method": method,
                "order_sha256": order_sha,
                "fields": order,
            }
        )

        sample = {
            "file_sha256": file_sha,
            "emitter": emitter,
            "method": method,
            "submethod": submethod,
            "producer": producer,
            "pdf_version": pdf_version,
            "page_count": doc.page_count,
            "object_count": doc.xref_length() - 1,
            "font_resources": sorted(entry[4] for entry in page_fonts),
            "image_dimensions": sorted([[entry[2], entry[3]] for entry in page_images]),
        }
        samples.append(sample)
        manifest_files.append(
            {
                "name": path.name,
                "sha256": file_sha,
                "bytes": len(pdf),
                "emitter": emitter,
                "method": method,
                "submethod": submethod,
                "pdf_version": pdf_version,
            }
        )
        doc.close()

    actual = {
        "pdf_count": len(samples),
        "methods": dict(sorted(Counter(row["method"] for row in samples).items())),
        "emitters": dict(sorted(Counter(row["emitter"] for row in samples).items())),
        "pdf_versions": dict(sorted(Counter(row["pdf_version"] for row in samples).items())),
    }
    if actual != EXPECTED:
        raise RuntimeError(f"corpus contract mismatch: expected={EXPECTED}, actual={actual}")
    if len(sbp_entries) != 37:
        raise RuntimeError(f"expected 37 SBP tuples, found {len(sbp_entries)}")

    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "immutability": "content-addressed corpus; changes require a new manifest filename/version",
        "corpus_root": str(CORPUS),
        "counts": actual,
        "files": manifest_files,
    }
    _write_artifact("manifest", manifest, immutable=True)

    field_variants: dict[str, dict[str, Any]] = {}
    for row in field_rows:
        variant = field_variants.setdefault(
            row["order_sha256"],
            {
                "order_sha256": row["order_sha256"],
                "fields": row["fields"],
                "sample_count": 0,
                "emitters": set(),
                "methods": set(),
            },
        )
        variant["sample_count"] += 1
        variant["emitters"].add(row["emitter"])
        variant["methods"].add(row["method"])
    variants = []
    for value in field_variants.values():
        value["emitters"] = sorted(value["emitters"])
        value["methods"] = sorted(value["methods"])
        variants.append(value)

    artifacts: dict[str, Any] = {
        "profiles": _profile_contracts(samples),
        "streams_images": {
            "schema": SCHEMA,
            "version": VERSION,
            "compressed_hash_policy": {
                "authenticity_signal": False,
                "purpose": "provenance observation and serializer diagnostics only",
            },
            "streams_by_file": streams_by_file,
            "static_images_by_file": images_by_file,
        },
        "sbp": {
            "schema": SCHEMA,
            "version": VERSION,
            "segmentation": [
                "[0] type",
                "[1:5] year/day",
                "[5:7] hour UTC",
                "[7:9] minute",
                "[9:11] second",
                "[11:17] reference",
                "[17] separator",
                "[18:22] channel",
                "[22:27] emitter core",
                "[27:32] route tail",
            ],
            "entry_count": len(sbp_entries),
            "entries": sbp_entries,
        },
        "fields": {
            "schema": SCHEMA,
            "version": VERSION,
            "variant_count": len(variants),
            "variants": sorted(variants, key=lambda row: row["order_sha256"]),
            "files": field_rows,
        },
        "fonts": {
            "schema": SCHEMA,
            "version": VERSION,
            "scope": "F1/G1 Tahoma-like embedded subsets",
            "files": fonts_by_file,
        },
        "glyphs": {
            "schema": SCHEMA,
            "version": VERSION,
            "normalization": {
                "coordinates": "font units divided by unitsPerEm, rounded to 6 decimals",
                "composites": "recursively decomposed to transformed contours",
                "component_gid_in_hash": False,
                "hash": "SHA-256 of canonical decomposed command geometry",
            },
            "geometry_count": len(geometries),
            "geometries": [
                {
                    **value,
                    "unicodes": sorted(value["unicodes"]),
                    "resources": sorted(value["resources"]),
                }
                for _, value in sorted(geometries.items())
            ],
            "observations": glyph_observations,
        },
    }
    for name, value in artifacts.items():
        _write_artifact(name, value)

    index_entries = {}
    for name in (
        "manifest",
        "profiles",
        "streams_images",
        "sbp",
        "fields",
        "fonts",
        "glyphs",
    ):
        path = OUT_DIR / ARTIFACTS[name]
        data = path.read_bytes()
        index_entries[name] = {
            "file": path.name,
            "bytes": len(data),
            "sha256": _sha(data),
        }
    index = {
        "schema": SCHEMA,
        "version": VERSION,
        "counts": actual,
        "artifacts": index_entries,
    }
    _write_artifact("index", index)
    return {
        "counts": actual,
        "sbp_entries": len(sbp_entries),
        "field_variants": len(variants),
        "geometry_count": len(geometries),
        "files": [str(OUT_DIR / ARTIFACTS[name]) for name in ARTIFACTS],
    }


def main() -> int:
    result = build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
