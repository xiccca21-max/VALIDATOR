"""
FontFile2 subset pool check — SHA256 fingerprint of embedded F1/F2/F3 TTF streams.

Corpus: ff2_corpus.json (build via tools/build_ff2_corpus.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

_CORPUS_PATH = Path(__file__).with_name("ff2_corpus.json")

_OBJ_HDR = re.compile(rb"(\d+)\s+0\s+obj")
_FONT_RES = re.compile(rb"/(F\d+)\s+(\d+)\s+0\s+R")

FONT_LAYERS = ("F1", "F2", "F3")


@dataclass
class FF2Flag:
    code: str
    detail: str


@dataclass
class FF2Result:
    flags: list[FF2Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _load_corpus() -> dict:
    if not _CORPUS_PATH.is_file():
        return {"version": 0, "layers": {}, "triplets": []}
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def _obj_spans(pdf: bytes) -> dict[int, bytes]:
    spans: dict[int, bytes] = {}
    for m in _OBJ_HDR.finditer(pdf):
        num = int(m.group(1))
        end = pdf.find(b"endobj", m.start())
        if end > 0:
            spans[num] = pdf[m.start() : end]
    return spans


def _font_resources(pdf: bytes) -> dict[str, int]:
    return {m.group(1).decode(): int(m.group(2)) for m in _FONT_RES.finditer(pdf)}


def _stream_bytes(obj_blob: bytes) -> bytes | None:
    pos = obj_blob.find(b"stream")
    if pos < 0:
        return None
    cs = pos + 6
    if obj_blob[cs : cs + 2] == b"\r\n":
        cs += 2
    elif obj_blob[cs : cs + 1] == b"\n":
        cs += 1
    es = obj_blob.find(b"endstream", cs)
    if es < 0:
        return None
    raw = obj_blob[cs:es]
    # Only remove the stream/endstream delimiter. Using rstrip() can remove a
    # real trailing 0x0a/0x0d byte from compressed font streams.
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n") or raw.endswith(b"\r"):
        raw = raw[:-1]
    if b"/Filter" in obj_blob[:pos] and b"/FlateDecode" in obj_blob[:pos]:
        try:
            return zlib.decompress(raw)
        except Exception:
            return None
    return raw


def _extract_fontfile2(pdf: bytes, font_key: str) -> bytes | None:
    spans = _obj_spans(pdf)
    res = _font_resources(pdf)
    num = res.get(font_key)
    if not num or num not in spans:
        return None
    blob = spans[num]
    dnum = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
    if dnum:
        blob = spans[int(dnum.group(1))]
    fd = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", blob)
    if not fd:
        return None
    fd_blob = spans[int(fd.group(1))]
    ff2 = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", fd_blob)
    if not ff2:
        return None
    ff2obj = spans[int(ff2.group(1))]
    return _stream_bytes(ff2obj)


def extract_ff2_fingerprints(pdf_bytes: bytes) -> dict[str, dict] | None:
    """
    Returns {F1: {sha256_16, size, sha256}, F2: ..., F3: ...} or None if incomplete.
    """
    out: dict[str, dict] = {}
    for layer in FONT_LAYERS:
        ttf = _extract_fontfile2(pdf_bytes, layer)
        if not ttf:
            return None
        full = hashlib.sha256(ttf).hexdigest()
        out[layer] = {
            "sha256": full,
            "sha256_16": full[:16],
            "size": len(ttf),
        }
    return out


def extract_fontfile2_streams(pdf_bytes: bytes) -> list[dict]:
    """Return every embedded FontFile2 stream with its short fingerprint."""
    return [
        {k: v for k, v in item.items() if k != "bytes"}
        for item in extract_fontfile2_stream_blobs(pdf_bytes)
    ]


def extract_fontfile2_stream_blobs(pdf_bytes: bytes) -> list[dict]:
    """Return every embedded FontFile2 stream including decoded TTF bytes."""
    spans = _obj_spans(pdf_bytes)
    out: list[dict] = []
    seen: set[int] = set()
    for _num, blob in spans.items():
        ff2 = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", blob)
        if not ff2:
            continue
        stream_num = int(ff2.group(1))
        if stream_num in seen or stream_num not in spans:
            continue
        seen.add(stream_num)
        ttf = _stream_bytes(spans[stream_num])
        if not ttf:
            continue
        full = hashlib.sha256(ttf).hexdigest()
        name = ""
        nm = re.search(rb"/FontName\s*/([^\s/>]+)", blob)
        if nm:
            name = nm.group(1).decode("latin1", "replace")
        out.append({
            "sha256": full,
            "sha256_16": full[:16],
            "size": len(ttf),
            "font_name": name,
            "bytes": ttf,
        })
    return out


def run_ff2_pool_check(pdf_bytes: bytes, corpus: dict | None = None) -> FF2Result:
    res = FF2Result()
    if corpus is None:
        corpus = _load_corpus()
    layers_pool: dict[str, set[str]] = {
        k: set(v) for k, v in corpus.get("layers", {}).items()
    }
    if not layers_pool.get("F1"):
        res.stats["ff2_corpus_missing"] = True
        return res

    fps = extract_ff2_fingerprints(pdf_bytes)
    if not fps:
        res.stats["ff2_extract_failed"] = True
        return res

    res.stats["ff2_fingerprints"] = {
        k: {"sha256_16": v["sha256_16"], "size": v["size"]} for k, v in fps.items()
    }
    res.stats["ff2_corpus_version"] = corpus.get("version")

    unknown: list[tuple[str, str, int]] = []
    for layer in FONT_LAYERS:
        h = fps[layer]["sha256_16"]
        pool = layers_pool.get(layer, set())
        if h not in pool:
            unknown.append((layer, h, fps[layer]["size"]))

    triplet = tuple(fps[layer]["sha256_16"] for layer in FONT_LAYERS)
    known_triplets = {tuple(t) for t in corpus.get("triplets", [])}
    res.stats["ff2_triplet"] = list(triplet)
    res.stats["ff2_triplet_known"] = triplet in known_triplets
    if unknown:
        res.stats["ff2_unknown_layers"] = [layer for layer, _, _ in unknown]

    # F1 (и часто F2) — subset под конкретный текст чека; новый оригинал даёт новый
    # hash при тех же F2/F3. Фейк — чужой стек шрифтов: все три слоя не из корпуса.
    if unknown and len(unknown) == len(FONT_LAYERS):
        bank_label = corpus.get("bank_name") or "банка"
        parts = ", ".join(f"{layer}={h} ({size} B)" for layer, h, size in unknown)
        res.flags.append(FF2Flag(
            "FF2_SUBSET_UNKNOWN",
            f"встроенные шрифты FontFile2 не встречались в {corpus.get('source_count', '?')} "
            f"настоящих чеках {bank_label} ({parts})",
        ))

    return res


def ff2_to_log_dict(result: FF2Result) -> dict:
    return {
        "flags": [{"code": f.code, "detail": f.detail} for f in result.flags],
        "stats": result.stats,
    }


# ── Corpus builder API ────────────────────────────────────────────────────────

def merge_ff2_corpus(samples: list[dict]) -> dict:
    layers: dict[str, set[str]] = {k: set() for k in FONT_LAYERS}
    triplets: set[tuple[str, str, str]] = set()
    sizes: dict[str, dict[str, list[int]]] = {k: {} for k in FONT_LAYERS}

    for sample in samples:
        fps = sample.get("fingerprints", {})
        if len(fps) != 3:
            continue
        t = tuple(fps[layer]["sha256_16"] for layer in FONT_LAYERS)
        triplets.add(t)
        for layer in FONT_LAYERS:
            h = fps[layer]["sha256_16"]
            layers[layer].add(h)
            sizes[layer].setdefault(h, []).append(fps[layer]["size"])

    return {
        "version": 1,
        "source_count": len(samples),
        "layers": {k: sorted(v) for k, v in layers.items()},
        "triplets": [list(t) for t in sorted(triplets)],
        "sizes": {
            layer: {h: {"min": min(sz), "max": max(sz)} for h, sz in hm.items()}
            for layer, hm in sizes.items()
        },
    }
