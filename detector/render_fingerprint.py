"""Отпечаток рендера страницы чека — горизонтальные полосы пикселей."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

_PATH = Path(__file__).with_name("tbank_render_rows.json")
_ROW_STEP = 8
_SCALE = 2.0


def _row_hashes(pdf_bytes: bytes) -> list[str]:
    if not fitz:
        return []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(_SCALE, _SCALE), alpha=False)
    doc.close()
    w, h = pix.width, pix.height
    return [
        hashlib.md5(bytes(pix.samples[y * w * 3 : (y + 1) * w * 3])).hexdigest()[:8]
        for y in range(0, h, _ROW_STEP)
    ]


def load_row_library() -> dict[int, set[str]]:
    if not _PATH.is_file():
        return {}
    raw = json.loads(_PATH.read_text(encoding="utf-8"))
    rows = raw.get("rows") or {}
    return {int(k): set(v) for k, v in rows.items()}


def save_row_library(lib: dict[int, set[str]], *, version: int | None = None) -> None:
    prev = {}
    if _PATH.is_file():
        try:
            prev = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    out = {
        "version": version if version is not None else int(prev.get("version", 1)),
        "row_step": _ROW_STEP,
        "scale": _SCALE,
        "source_count": int(prev.get("source_count", 0)),
        "rows": {str(k): sorted(v) for k, v in sorted(lib.items())},
    }
    _PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_rows_into_library(pdf_bytes: bytes, lib: dict[int, set[str]] | None = None) -> dict[int, set[str]]:
    lib = dict(lib or load_row_library())
    for ri, h in enumerate(_row_hashes(pdf_bytes)):
        lib.setdefault(ri, set()).add(h)
    return lib


def count_foreign_rows(pdf_bytes: bytes, lib: dict[int, set[str]] | None = None) -> tuple[int, int]:
    """(foreign_count, total_rows_with_baseline)."""
    lib = lib or load_row_library()
    if not lib:
        return 0, 0
    rows = _row_hashes(pdf_bytes)
    bad = 0
    checked = 0
    for ri, h in enumerate(rows):
        if ri not in lib:
            continue
        checked += 1
        if h not in lib[ri]:
            bad += 1
    return bad, checked


def run_render_row_check(pdf_bytes: bytes) -> tuple[int, int, str]:
    bad, checked = count_foreign_rows(pdf_bytes)
    if checked == 0:
        return bad, checked, "библиотека рендера пуста"
    return bad, checked, f"{bad} чужих полос из {checked} (шаг {_ROW_STEP}px)"
