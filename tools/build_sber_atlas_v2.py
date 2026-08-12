#!/usr/bin/env python3
"""Build versioned Sber v2 atlas from the 22-PDF originals corpus.

Hashes / novel producers / subset prefixes are diagnostic-only observations,
never solo HARD authenticity contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    fitz = None

ROOT = Path(__file__).resolve().parents[1]
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\сбер")
OUT = ROOT / "detector" / "sber_v2" / "atlas_data" / "sber_atlas_v2.json"

SCHEMA = "sber-v2-atlas"
VERSION = "1.0.0"

from detector.sber_profiles import (  # noqa: E402
    classify_submethod,
    detect_generator_path,
    extract_sbp_opid,
    is_sber_receipt,
)
from detector.sber_v2.rules import LEGACY_TO_PROFILE, PROFILE_LABELS  # noqa: E402
from detector.structure import content_skeleton_hash, content_stream_bytes, find_streams  # noqa: E402

_SBP_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj")
_FONTFILE2_RE = re.compile(rb"/FontFile2\s+(\d+)\s+\d+\s+R")
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\n?endstream", re.S)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdf_meta(pdf_bytes: bytes) -> tuple[str, str, str, float, float]:
    if not fitz:
        return "", "", "", 0.0, 0.0
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    meta = doc.metadata or {}
    page = doc[0] if doc.page_count else None
    w = float(page.rect.width) if page else 0.0
    h = float(page.rect.height) if page else 0.0
    text = page.get_text() if page else ""
    doc.close()
    return (
        meta.get("producer") or "",
        meta.get("creator") or "",
        text,
        w,
        h,
    )


def _stream_roles(pdf_bytes: bytes) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    for raw, dec in find_streams(pdf_bytes):
        role = "other"
        if dec and b"BT" in dec and (b"Tj" in dec or b"TJ" in dec):
            role = "page_content"
        elif raw[:2] == b"\xff\xd8":
            role = "image_jpeg"
        elif len(dec) > 100 and (b"cmap" in dec[:200].lower() or b"begincmap" in dec):
            role = "tounicode"
        elif len(raw) > 200 and raw[:4] in (b"\x00\x01\x00\x00", b"OTTO"):
            role = "fontfile2"
        roles.append({
            "role": role,
            "compressed_len": len(raw),
            "decoded_len": len(dec or b""),
            "compressed_sha256": _sha(raw)[:16],
            "zlib_header": raw[:2].hex() if len(raw) >= 2 else "",
        })
    return roles


def _fontfile2_hashes(pdf_bytes: bytes) -> list[str]:
    hashes: list[str] = []
    for m in _FONTFILE2_RE.finditer(pdf_bytes):
        onum = int(m.group(1))
        pat = re.compile(rf"{onum}\s+0\s+obj(.*?)endobj".encode(), re.S)
        om = pat.search(pdf_bytes)
        if not om:
            continue
        sm = _STREAM_RE.search(om.group(1))
        if not sm:
            continue
        raw = sm.group(1)
        try:
            dec = zlib.decompress(raw)
        except Exception:
            dec = raw
        hashes.append(_sha(dec)[:16])
    return hashes


def _image_hashes(pdf_bytes: bytes) -> list[str]:
    out: list[str] = []
    for raw, dec in find_streams(pdf_bytes):
        payload = dec or raw
        if payload[:2] == b"\xff\xd8" or b"/Subtype /Image" in pdf_bytes:
            if payload[:2] == b"\xff\xd8" or (dec and len(dec) > 500 and b"BT" not in dec[:50]):
                if payload[:2] == b"\xff\xd8":
                    out.append(_sha(payload)[:16])
    # Prefer explicit image streams via fitz
    if fitz:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for i in range(doc.page_count):
                for img in doc.get_page_images(i) or []:
                    xref = img[0]
                    try:
                        data = doc.extract_image(xref)
                        if data and data.get("image"):
                            out.append(_sha(data["image"])[:16])
                    except Exception:
                        pass
            doc.close()
        except Exception:
            pass
    return sorted(set(out))


def _sbp_slots(opid: str | None) -> dict[str, Any] | None:
    if not opid or not _SBP_RE.match(opid):
        return None
    return {
        "marker": opid[0],
        "core": opid[1:11],
        "tail": opid[11:32],
        "tail_prefix4": opid[11:15],
        "tail_suffix4": opid[28:32],
    }


def _geometry_anchors(text: str, pdf_bytes: bytes) -> dict[str, Any]:
    """Stub label Y-order from text lines (refined in Phase 4)."""
    labels = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        for key in (
            "сумма", "комиссия", "получатель", "отправитель", "дата",
            "номер операции", "сколько", "списано", "банк получателя",
        ):
            if key in low and len(s) < 80:
                labels.append(s[:60])
                break
    return {"label_order_stub": labels[:20]}


def analyze_file(path: Path) -> dict[str, Any]:
    pdf_bytes = path.read_bytes()
    producer, creator, text, w, h = _pdf_meta(pdf_bytes)
    legacy = classify_submethod(text, producer=producer, creator=creator)
    profile_id = LEGACY_TO_PROFILE.get(legacy, "unknown")
    generator = detect_generator_path(producer, creator)
    opid = extract_sbp_opid(text)
    return {
        "file": path.name,
        "file_sha256": _sha(pdf_bytes),
        "is_sber": is_sber_receipt(text, pdf_bytes),
        "legacy_submethod": legacy,
        "profile_id": profile_id,
        "profile_label": PROFILE_LABELS.get(profile_id, ""),
        "producer": producer,
        "creator": creator,
        "generator_path": generator,
        "page_size": [round(w, 2), round(h, 2)],
        "object_count": len(_OBJ_RE.findall(pdf_bytes)),
        "content_skeleton": content_skeleton_hash(pdf_bytes),
        "content_len": len(content_stream_bytes(pdf_bytes) or b""),
        "stream_roles": _stream_roles(pdf_bytes),
        "fontfile2_sha16": _fontfile2_hashes(pdf_bytes),
        "image_sha16": _image_hashes(pdf_bytes),
        "sbp_opid": opid,
        "sbp_slots": _sbp_slots(opid),
        "geometry_anchors": _geometry_anchors(text, pdf_bytes),
    }


def aggregate(files: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        by_profile[f["profile_id"]].append(f)

    profiles: dict[str, Any] = {}
    for pid, items in by_profile.items():
        gens = Counter(i["generator_path"] for i in items)
        producers = sorted({i["producer"] for i in items if i["producer"]})
        skeletons = sorted({i["content_skeleton"] for i in items if i["content_skeleton"]})
        page_sizes = sorted({tuple(i["page_size"]) for i in items})
        font_hashes = sorted({h for i in items for h in i["fontfile2_sha16"]})
        image_hashes = sorted({h for i in items for h in i["image_sha16"]})
        sbp_markers = sorted({
            (i["sbp_slots"] or {}).get("marker")
            for i in items if i.get("sbp_slots")
        } - {None})
        sbp_tail_p4 = sorted({
            (i["sbp_slots"] or {}).get("tail_prefix4")
            for i in items if i.get("sbp_slots")
        } - {None})
        stream_role_sets = [
            tuple(sorted(Counter(r["role"] for r in i["stream_roles"]).items()))
            for i in items
        ]
        profiles[pid] = {
            "count": len(items),
            "label": PROFILE_LABELS.get(pid, pid),
            "generator_paths": dict(gens),
            "producers": producers,
            "content_skeletons": skeletons,
            "page_sizes": [list(ps) for ps in page_sizes],
            "fontfile2_sha16": font_hashes,
            "image_sha16": image_hashes,
            "sbp_markers": sbp_markers,
            "sbp_tail_prefix4": sbp_tail_p4,
            "stream_role_histograms": [
                {k: v for k, v in hist} for hist in sorted(set(stream_role_sets))
            ],
            "files": [i["file"] for i in items],
        }

    sbp_combinations = []
    for f in files:
        slots = f.get("sbp_slots")
        if slots:
            sbp_combinations.append({
                "marker": slots["marker"],
                "tail_prefix4": slots["tail_prefix4"],
                "tail_suffix4": slots["tail_suffix4"],
                "file": f["file"],
                "profile_id": f["profile_id"],
            })

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "corpus_root": str(CORPUS),
        "pdf_count": len(files),
        "profile_counts": {k: v["count"] for k, v in profiles.items()},
        "profiles": profiles,
        "sbp_empirical": {
            "combinations": sbp_combinations,
            "markers": sorted({c["marker"] for c in sbp_combinations}),
            "tail_prefix4": sorted({c["tail_prefix4"] for c in sbp_combinations}),
        },
        "files": files,
        "notes": [
            "static image/font hashes are diagnostics only — never solo HARD",
            "unknown coherent profile must yield НЕИЗВЕСТНЫЙ ДОКУМЕНТ, not ФЕЙК",
            "sber_internal_pdfium is a legitimate Sber profile",
        ],
    }


def main() -> None:
    pdfs = sorted(CORPUS.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs in {CORPUS}")
    files = [analyze_file(p) for p in pdfs]
    atlas = aggregate(files)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(atlas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({atlas['pdf_count']} files)")
    print("profiles:", atlas["profile_counts"])
    unknown = [f["file"] for f in files if f["profile_id"] == "unknown"]
    if unknown:
        print("UNKNOWN:", unknown)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
