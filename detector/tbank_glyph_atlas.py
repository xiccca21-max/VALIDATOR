"""K-TBANK-GLYPH-ATLAS-001 v3 — full Unicode→CID→GID→glyf atlas and cross-layer validator."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .font_layers import _font_objects
from .glyf_fingerprint import (
    _collect_used_by_font,
    _extract_fontfile2,
    _font_cid_maps,
    _obj_spans,
    _font_resources,
)
from .pdf_forensics import _glyph_outline_hash, _ttf_tables
from .structure import content_stream_bytes
from .tbank_sbp_geometry import (
    _glyph_advance,
    _parse_content_runs,
)

_ATLAS_DIR = Path(__file__).with_name("atlas_data")
_ATLAS_INDEX = _ATLAS_DIR / "tbank_glyph_atlas_index.json"
_ATLAS_LEGACY = Path(__file__).with_name("tbank_glyph_atlas.json")
_RULE_ID = "K-TBANK-GLYPH-ATLAS-001"
_ATLAS_VERSION = "3.0.0"
_FONT_ROLES = {
    "F1": "TinkoffSans-Regular",
    "F2": "TinkoffSans-Medium",
    "F3": "ALSRubl",
}
_GENERATION = "jasper_openpdf_tbank_v6"
_RENDER_TOL_PT = 0.75
_W_PER_FONT_RE = re.compile(rb"/W\s*\[")
_DW_RE = re.compile(rb"/DW\s+(-?\d+)")
_CMAP_OBJ_RE = re.compile(rb"/Encoding\s+(\d+)\s+0\s+R")
_MAX_POINTS_STORED = 512


@dataclass
class HardFlag:
    code: str
    detail: str
    rule_id: str = _RULE_ID


@dataclass
class AtlasResult:
    flags: list[HardFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def _glyph_key(font: str, unicode_cp: int, cid: int) -> str:
    return f"{unicode_cp:04X}:{cid:04X}"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_key(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _table_sha256(ttf: bytes, tag: bytes) -> str | None:
    entry = _ttf_tables(ttf).get(tag)
    if not entry:
        return None
    off, ln = entry
    return hashlib.sha256(ttf[off:off + ln]).hexdigest()


def _table_padding(ttf: bytes) -> dict[str, int]:
    tables = _ttf_tables(ttf)
    if not tables:
        return {}
    ordered = sorted(tables.items(), key=lambda x: x[1][0])
    padding: dict[str, int] = {}
    for i in range(len(ordered) - 1):
        tag_a, (off_a, ln_a) = ordered[i]
        tag_b, (off_b, _) = ordered[i + 1]
        gap = off_b - (off_a + ln_a)
        key = f"{tag_a.decode('latin1', 'replace')}->{tag_b.decode('latin1', 'replace')}"
        padding[key] = gap
    return padding


def _parse_w_array(blob: bytes) -> dict[int, int]:
    widths: dict[int, int] = {}
    m = _W_PER_FONT_RE.search(blob)
    if not m:
        return widths
    start = m.end() - 1
    depth = 0
    end = start
    for i in range(start, min(len(blob), start + 12000)):
        ch = blob[i:i + 1]
        if ch == b"[":
            depth += 1
        elif ch == b"]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    arr = blob[start:end]
    for mm in re.finditer(rb"(\d+)\s*\[([^\]]*)\]", arr):
        c0 = int(mm.group(1))
        nums = [int(x) for x in re.findall(rb"\d+", mm.group(2))]
        for k, w in enumerate(nums):
            widths[c0 + k] = w
    arr2 = re.sub(rb"\d+\s*\[[^\]]*\]", b" ", arr)
    for mm in re.finditer(rb"(\d+)\s+(\d+)\s+(\d+)", arr2):
        c1, c2, w = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
        for cid in range(c1, c2 + 1):
            widths[cid] = w
    return widths


def _font_descendant_blob(pdf: bytes, font_key: str) -> bytes:
    spans = _obj_spans(pdf)
    res = _font_resources(pdf)
    num = res.get(font_key)
    if not num:
        return b""
    blob = spans.get(num, b"")
    dnum = re.search(rb"/DescendantFonts\s*\[\s*(\d+)", blob)
    if dnum:
        blob = spans.get(int(dnum.group(1)), b"")
    return blob


def _font_w_and_dw(pdf: bytes, font_key: str) -> tuple[dict[int, int], int | None, bytes]:
    blob = _font_descendant_blob(pdf, font_key)
    dw_m = _DW_RE.search(blob)
    dw = int(dw_m.group(1)) if dw_m else None
    w_m = _W_PER_FONT_RE.search(blob)
    w_raw = w_m.group(0) if w_m else b""
    return _parse_w_array(blob), dw, w_raw


def _composite_closure(ttf: bytes, root_gids: set[int]) -> set[int]:
    if not TTFont or not ttf:
        return set(root_gids)
    try:
        tt = TTFont(BytesIO(ttf))
        order = tt.getGlyphOrder()
        closure = set(root_gids)
        stack = list(root_gids)
        while stack:
            gid = stack.pop()
            if gid < 0 or gid >= len(order):
                continue
            g = tt["glyf"][order[gid]]
            if not getattr(g, "isComposite", lambda: False)():
                continue
            for comp in g.components:
                cname = comp.glyphName
                if cname in order:
                    cg = order.index(cname)
                    if cg not in closure:
                        closure.add(cg)
                        stack.append(cg)
        return closure
    except Exception:
        return set(root_gids)


def _glyph_detail(ttf: bytes, gid: int) -> dict[str, Any]:
    if not TTFont or not ttf:
        return {}
    try:
        tt = TTFont(BytesIO(ttf))
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return {"missing": True}
        gname = order[gid]
        g = tt["glyf"][gname]
        is_composite = bool(getattr(g, "isComposite", lambda: False)())
        try:
            g.expand(tt["glyf"])
        except Exception:
            pass
        coords = getattr(g, "coordinates", None) or []
        on_curve = [int(x) for x in (getattr(g, "flags", None) or [])]
        bbox = [int(g.xMin), int(g.yMin), int(g.xMax), int(g.yMax)] if hasattr(g, "xMin") else [0, 0, 0, 0]
        components: list[dict[str, Any]] = []
        if is_composite:
            try:
                # Re-read pre-expand composite from a fresh TTFont glyph if needed.
                g0 = TTFont(BytesIO(ttf))["glyf"][gname] if TTFont else g
                for comp in getattr(g0, "components", []) or []:
                    transform = None
                    raw_tf = getattr(comp, "transform", None)
                    if raw_tf:
                        try:
                            transform = [
                                raw_tf[0], raw_tf[1], raw_tf[2], raw_tf[3],
                                getattr(comp, "x", 0), getattr(comp, "y", 0),
                            ]
                        except Exception:
                            transform = None
                    components.append({
                        "glyphName": getattr(comp, "glyphName", ""),
                        "transform": transform,
                    })
            except Exception:
                components = []
        # Prefer loca/glyf table bytes — fontTools compile() is version-unstable
        # and false-positives GLYPH_OUTLINE_MISMATCH on originals.
        raw_glyf = b""
        try:
            glyf_tbl = tt["glyf"]
            if hasattr(glyf_tbl, "getGlyphData"):
                raw_glyf = bytes(glyf_tbl.getGlyphData(gname) or b"")
            if not raw_glyf and not is_composite and hasattr(g, "compile"):
                compiled = g.compile(glyf_tbl)
                if isinstance(compiled, (bytes, bytearray)):
                    raw_glyf = bytes(compiled)
        except Exception:
            raw_glyf = b""
        prog = getattr(g, "program", None)
        try:
            if prog is None:
                program = b""
            elif isinstance(prog, (bytes, bytearray)):
                program = bytes(prog)
            elif hasattr(prog, "getBytecode"):
                program = bytes(prog.getBytecode() or b"")
            else:
                program = b""
        except Exception:
            program = b""
        hmtx_adv, hmtx_lsb = (0, 0)
        if "hmtx" in tt:
            hmtx_adv, hmtx_lsb = tt["hmtx"][gname]
        norm_pts = [[round(float(x), 1), round(float(y), 1)] for x, y in coords[:_MAX_POINTS_STORED]]
        return {
            "gid": gid,
            "glyph_name": gname,
            "contour_count": int(getattr(g, "numberOfContours", 0) or 0),
            "point_count": len(coords),
            "bbox": bbox,
            "normalized_points": norm_pts,
            "on_curve_flags": on_curve[:_MAX_POINTS_STORED],
            "composite_components": components,
            "raw_glyf_hash": _hash_bytes(raw_glyf) if raw_glyf else "",
            # Prefer stable loca bytes for outline id; fall back to legacy compile hash.
            "outline_norm_hash": (
                hashlib.sha1(raw_glyf).hexdigest()[:12]
                if raw_glyf
                else (_glyph_outline_hash(ttf, gid) or "")
            ),
            "instruction_bytecode_hex": program.hex(),
            "instruction_bytecode_hash": _hash_bytes(program) if program else "",
            "instruction_bytecode_len": len(program),
            "points_fingerprint": _hash_bytes(json.dumps(norm_pts, separators=(",", ":")).encode()),
            "on_curve_fingerprint": _hash_bytes(bytes(on_curve[:500])),
            "hmtx_advanceWidth": int(hmtx_adv),
            "hmtx_leftSideBearing": int(hmtx_lsb),
            "loca_record_length": len(raw_glyf) if raw_glyf else 0,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _tounicode_raw(pdf: bytes, font_key: str) -> bytes:
    spans = _obj_spans(pdf)
    res = _font_resources(pdf)
    num = res.get(font_key)
    if not num:
        return b""
    for blob in (spans.get(num, b""), _font_descendant_blob(pdf, font_key)):
        for tu in re.finditer(rb"/ToUnicode\s+(\d+)\s+0\s+R", blob):
            return spans.get(int(tu.group(1)), b"")
    return b""


def _cmap_raw(pdf: bytes, font_key: str) -> bytes:
    spans = _obj_spans(pdf)
    res = _font_resources(pdf)
    num = res.get(font_key)
    if not num:
        return b""
    blob = spans.get(num, b"")
    enc = _CMAP_OBJ_RE.search(blob)
    if enc:
        return spans.get(int(enc.group(1)), b"")
    return _tounicode_raw(pdf, font_key)


def subset_builder_fingerprint(pdf: bytes, font_key: str) -> dict[str, Any]:
    ttf = _extract_fontfile2(pdf, font_key)
    if not ttf:
        return {}
    tables = _ttf_tables(ttf)
    order = [t.decode("latin1", "replace") for t in tables]
    table_hashes = {tag.decode("latin1", "replace"): _table_sha256(ttf, tag) for tag in tables}
    used = _collect_used_by_font(pdf)
    used_gids = set(used.get(font_key, set()))
    closure = sorted(_composite_closure(ttf, used_gids))
    head = hhea = maxp = {}
    glyph_order: list[str] = []
    if TTFont:
        try:
            tt = TTFont(BytesIO(ttf))
            glyph_order = tt.getGlyphOrder()
            if "head" in tt:
                h = tt["head"]
                head = {
                    "unitsPerEm": h.unitsPerEm,
                    "xMin": h.xMin, "yMin": h.yMin,
                    "xMax": h.xMax, "yMax": h.yMax,
                    "created": int(h.created),
                    "modified": int(h.modified),
                }
            if "hhea" in tt:
                hh = tt["hhea"]
                hhea = {
                    "ascent": hh.ascent, "descent": hh.descent,
                    "numberOfHMetrics": hh.numberOfHMetrics,
                }
            if "maxp" in tt:
                mp = tt["maxp"]
                maxp = {
                    "numGlyphs": mp.numGlyphs,
                    "maxPoints": getattr(mp, "maxPoints", None),
                    "maxContours": getattr(mp, "maxContours", None),
                }
        except Exception:
            pass
    _, _, w_raw = _font_w_and_dw(pdf, font_key)
    tu_raw = _tounicode_raw(pdf, font_key)
    cmap_raw = _cmap_raw(pdf, font_key)
    return {
        "font_role": font_key,
        "family": _FONT_ROLES.get(font_key, font_key),
        "generation": _GENERATION,
        "ttf_table_order": order,
        "table_offsets": {k.decode("latin1", "replace"): list(v) for k, v in tables.items()},
        "table_padding": _table_padding(ttf),
        "table_hashes": table_hashes,
        "fontfile2_sha256": _hash_bytes(ttf),
        "tounicode_serialization": tu_raw.decode("latin1", "replace")[:4000],
        "tounicode_serialization_hash": _hash_bytes(tu_raw),
        "cmap_serialization": cmap_raw.decode("latin1", "replace")[:4000],
        "cmap_serialization_hash": _hash_bytes(cmap_raw),
        "w_serialization": w_raw.decode("latin1", "replace")[:4000],
        "w_serialization_hash": _hash_bytes(w_raw),
        "used_gid_set": sorted(used_gids),
        "composite_closure": closure,
        "glyph_packing_order": glyph_order,
        "head": head,
        "hhea": hhea,
        "maxp": maxp,
    }


def _fitz_text_spans(pdf: bytes) -> list[dict[str, Any]]:
    if not fitz:
        return []
    out: list[dict[str, Any]] = []
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
        page = doc[0] if doc.page_count else None
        if not page:
            doc.close()
            return out
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    bbox = sp.get("bbox") or (0, 0, 0, 0)
                    out.append({
                        "text": sp.get("text", ""),
                        "x": float(bbox[0]),
                        "y": float(bbox[1]),
                        "end_x": float(bbox[2]),
                        "width": float(bbox[2]) - float(bbox[0]),
                    })
        doc.close()
    except Exception:
        pass
    return out


def _match_fitz_span(run: dict[str, Any], spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = run.get("text", "")
    if not text.strip():
        return None
    y, x = run.get("y", 0), run.get("x", 0)
    best, best_score = None, 999.0
    for sp in spans:
        if sp.get("text", "") != text:
            continue
        dy, dx = abs(sp.get("y", 0) - y), abs(sp.get("x", 0) - x)
        if dy > 1.5:
            continue
        score = dy * 10 + dx
        if score < best_score:
            best_score, best = score, sp
    return best


def extract_glyph_observations(pdf: bytes, *, source: str = "") -> dict[str, Any]:
    cid_maps = _font_cid_maps(pdf)
    fonts, _ = _font_objects(pdf)
    content = content_stream_bytes(pdf) or b""
    runs = _parse_content_runs(content, fonts) if content else []
    fitz_spans = _fitz_text_spans(pdf)
    w_maps = {fk: _font_w_and_dw(pdf, fk) for fk in _FONT_ROLES}
    glyphs: dict[str, dict[str, dict[str, Any]]] = {fk: {} for fk in _FONT_ROLES}
    render_runs: list[dict[str, Any]] = []

    for run in runs:
        font = run.get("font", "")
        if font not in _FONT_ROLES:
            continue
        ttf = _extract_fontfile2(pdf, font)
        cmap = cid_maps.get(font, {}) or fonts.get(font, {}).get("cmap", {})
        w_dict, dw, w_raw = w_maps.get(font, ({}, None, b""))
        cids = run.get("cids", [])
        tj_raw_hex = run.get("tj_raw_hex", "")
        text = run.get("text", "")
        calc_width = float(run.get("width", 0))
        fitz_sp = _match_fitz_span(run, fitz_spans)
        fitz_width = fitz_sp.get("width") if fitz_sp else None
        render_runs.append({
            "font": font,
            "text": text,
            "calc_width": calc_width,
            "fitz_width": fitz_width,
            "width_delta": abs(calc_width - fitz_width) if fitz_width is not None else None,
        })
        for cid in cids:
            ch = cmap.get(cid, "")
            cp = ord(ch[0]) if ch else -1
            if cp < 0:
                continue
            gid = cid
            detail = _glyph_detail(ttf or b"", gid)
            pdf_w = w_dict.get(cid, dw)
            fs = float(run.get("font_size", 9))
            key = _glyph_key(font, cp, cid)
            entry = {
                "font_role": font,
                "family": _FONT_ROLES[font],
                "generation": _GENERATION,
                "unicode": ch,
                "codepoint": cp,
                "raw_tj_bytes_hex": tj_raw_hex,
                "cid": cid,
                "gid": gid,
                "tounicode_mapping": ch,
                "cid_to_gid_mapping": "Identity",
                "pdf_w_width": pdf_w,
                "pdf_dw": dw,
                "calculated_advance_pt": round(_glyph_advance(cid, w_dict, fs, dw=dw or 1000), 4),
                **detail,
            }
            slot = glyphs[font].setdefault(key, entry)
            if slot is not entry:
                _merge_unique(slot, "raw_tj_bytes_hex", tj_raw_hex)

    builders = {fk: subset_builder_fingerprint(pdf, fk) for fk in _FONT_ROLES}
    return {
        "source": source,
        "glyphs": glyphs,
        "subset_builders": builders,
        "render_runs": render_runs,
    }


def _merge_unique(dst: dict, key: str, val: Any) -> None:
    if val is None or val == "" or val == []:
        return
    if isinstance(val, list):
        for item in val:
            _merge_unique(dst, key, item)
        return
    cur = dst.get(key)
    if cur is None:
        dst[key] = val
        return
    if isinstance(cur, list):
        if val not in cur:
            cur.append(val)
    elif cur != val:
        dst[key] = [cur, val]


def _merge_glyph_entry(acc: dict, obs: dict) -> None:
    scalar_lists = (
        "raw_tj_bytes_hex", "raw_glyf_hash", "outline_norm_hash",
        "points_fingerprint", "on_curve_fingerprint", "instruction_bytecode_hash",
        "hmtx_advanceWidth", "hmtx_leftSideBearing", "pdf_w_width", "pdf_dw",
        "contour_count", "point_count", "loca_record_length", "calculated_advance_pt",
    )
    for mf in scalar_lists:
        if mf in obs:
            _merge_unique(acc, mf, obs[mf])

    if "bbox" in obs:
        _merge_unique(acc, "bboxes", obs["bbox"])

    comps = obs.get("composite_components") or []
    if comps:
        ck = _json_key(comps)
        seen = acc.setdefault("_composite_keys", [])
        if ck not in seen:
            seen.append(ck)
            acc.setdefault("composite_components_variants", []).append(comps)

    pts = obs.get("normalized_points")
    if pts:
        pf = obs.get("points_fingerprint", _hash_bytes(json.dumps(pts, separators=(",", ":")).encode()))
        variants = acc.setdefault("normalized_points_variants", {})
        if pf not in variants:
            variants[pf] = pts

    flags = obs.get("on_curve_flags")
    if flags is not None:
        ofp = obs.get("on_curve_fingerprint", _hash_bytes(bytes(flags[:500])))
        ovars = acc.setdefault("on_curve_variants", {})
        if ofp not in ovars:
            ovars[ofp] = flags

    ibhex = obs.get("instruction_bytecode_hex")
    if ibhex:
        _merge_unique(acc, "instruction_bytecode_hex_variants", ibhex)

    if "canonical" not in acc and pts:
        acc["canonical"] = {
            "normalized_points": pts,
            "on_curve_flags": flags or [],
            "instruction_bytecode_hex": ibhex or "",
            "composite_components": comps,
            "bbox": obs.get("bbox"),
        }


def merge_atlas_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_font: dict[str, dict[str, dict]] = {fk: {} for fk in _FONT_ROLES}
    builder_obs: list[dict[str, Any]] = []
    render_deltas: list[float] = []

    for sample in samples:
        builder_obs.append({
            "source": sample.get("source", ""),
            "builders": sample.get("subset_builders", {}),
        })
        for rr in sample.get("render_runs", []):
            d = rr.get("width_delta")
            if d is not None:
                render_deltas.append(float(d))
        for font, gmap in sample.get("glyphs", {}).items():
            if font not in by_font:
                continue
            for gkey, obs in gmap.items():
                acc = by_font[font].setdefault(gkey, {
                    "font_role": obs["font_role"],
                    "family": obs["family"],
                    "generation": obs["generation"],
                    "unicode": obs["unicode"],
                    "codepoint": obs["codepoint"],
                    "cid": obs["cid"],
                    "gid": obs["gid"],
                    "tounicode_mapping": obs.get("tounicode_mapping", obs.get("unicode", "")),
                    "cid_to_gid_mapping": obs.get("cid_to_gid_mapping", "Identity"),
                })
                _merge_glyph_entry(acc, obs)

    for font in by_font:
        for gkey, acc in by_font[font].items():
            acc.pop("_composite_keys", None)
            canon = acc.get("canonical")
            if canon:
                acc["normalized_points"] = canon.get("normalized_points", [])
                acc["on_curve_flags"] = canon.get("on_curve_flags", [])
                acc["instruction_bytecode_hex"] = canon.get("instruction_bytecode_hex", "")
                acc["composite_components"] = canon.get("composite_components", [])
                if canon.get("bbox"):
                    acc["bbox"] = canon["bbox"]

    render_stats = {}
    if render_deltas:
        sd = sorted(render_deltas)
        render_stats = {
            "samples": len(render_deltas),
            "max_delta_pt": round(max(render_deltas), 4),
            "p95_delta_pt": round(sd[int(len(sd) * 0.95)], 4),
        }

    return {
        "version": _ATLAS_VERSION,
        "rule_id": _RULE_ID,
        "fonts": {
            fk: {"family": _FONT_ROLES[fk], "glyph_count": len(by_font[fk]), "glyphs": by_font[fk]}
            for fk in _FONT_ROLES
        },
        "subset_builder_observations": builder_obs,
        "render_stats": render_stats,
        "total_glyph_count": sum(len(by_font[fk]) for fk in _FONT_ROLES),
    }


def save_atlas_bundle(data: dict[str, Any]) -> dict[str, Path]:
    _ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    index = {
        "version": data["version"],
        "rule_id": data["rule_id"],
        "total_glyph_count": data["total_glyph_count"],
        "render_stats": data.get("render_stats", {}),
        "font_files": {},
    }
    for fk in _FONT_ROLES:
        font_data = data["fonts"][fk]
        p = _ATLAS_DIR / f"tbank_glyph_atlas_{fk}.json"
        p.write_text(json.dumps(font_data, ensure_ascii=False, indent=2), encoding="utf-8")
        paths[fk] = p
        index["font_files"][fk] = p.name
    sb_path = _ATLAS_DIR / "tbank_subset_builder_atlas.json"
    sb_path.write_text(
        json.dumps({
            "version": data["version"],
            "rule_id": data["rule_id"],
            "observations": data.get("subset_builder_observations", []),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["subset_builder"] = sb_path
    index["subset_builder_file"] = sb_path.name
    _ATLAS_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["index"] = _ATLAS_INDEX
    legacy_glyphs = {}
    for fk in _FONT_ROLES:
        for gkey, gval in data["fonts"][fk]["glyphs"].items():
            legacy_glyphs[f"{fk}:{gkey}"] = gval
    legacy = {
        "version": data["version"],
        "rule_id": data["rule_id"],
        "glyph_count": data["total_glyph_count"],
        "glyphs": legacy_glyphs,
        "render_stats": data.get("render_stats", {}),
    }
    _ATLAS_LEGACY.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["legacy"] = _ATLAS_LEGACY
    return paths


def load_atlas() -> dict[str, Any]:
    if _ATLAS_INDEX.is_file():
        index = json.loads(_ATLAS_INDEX.read_text(encoding="utf-8"))
        glyphs: dict[str, Any] = {}
        for fk, fname in index.get("font_files", {}).items():
            fp = _ATLAS_DIR / fname
            if not fp.is_file():
                continue
            font_data = json.loads(fp.read_text(encoding="utf-8"))
            for gkey, gval in font_data.get("glyphs", {}).items():
                glyphs[f"{fk}:{gkey}"] = gval
        return {"version": index.get("version", "0"), "glyphs": glyphs, "index": index}
    if _ATLAS_LEGACY.is_file():
        return json.loads(_ATLAS_LEGACY.read_text(encoding="utf-8"))
    return {"version": "0", "glyphs": {}}


def save_atlas(data: dict[str, Any]) -> Path:
    paths = save_atlas_bundle(data)
    return paths["index"]


def _atlas_allowed(ref: dict, field: str, cur_val: Any) -> bool:
    allowed = ref.get(field, [])
    if not isinstance(allowed, list):
        allowed = [allowed] if allowed else []
    return not allowed or not cur_val or cur_val in allowed


def validate_glyph_atlas(pdf: bytes, atlas: dict[str, Any] | None = None) -> AtlasResult:
    res = AtlasResult()
    if atlas is None:
        atlas = load_atlas()
    if not atlas.get("glyphs"):
        res.stats["atlas_missing"] = True
        return res

    obs = extract_glyph_observations(pdf)
    atlas_glyphs = atlas["glyphs"]
    all_glyphs: dict[str, dict] = {}
    for font, gmap in obs.get("glyphs", {}).items():
        for gkey, gval in gmap.items():
            all_glyphs[f"{font}:{gkey}"] = gval

    res.stats["used_glyph_keys"] = len(all_glyphs)
    render_mismatches = 0

    for full_key, cur in all_glyphs.items():
        font = cur["font_role"]
        ch = cur.get("unicode", "")
        cid = cur["cid"]

        if not ch:
            res.flags.append(HardFlag(
                "USED_CID_MISSING_FROM_CMAP",
                f"{font}: CID {cid} в Tj без ToUnicode",
            ))
            continue

        if cur.get("missing") or (cur.get("contour_count", 1) == 0 and ch.strip() and ch not in " \t"):
            res.flags.append(HardFlag(
                "BROKEN_GLYPH_ZERO_LENGTH",
                f"{font}: {ch!r} CID/GID {cid} — пустой glyf",
            ))

        ha = cur.get("hmtx_advanceWidth")
        pw = cur.get("pdf_w_width")
        if ha is not None and pw is not None and abs(int(ha) - int(pw)) > 2:
            res.flags.append(HardFlag(
                "CMAP_W_MISMATCH",
                f"{font}: {ch!r} CID {cid} — hmtx={ha} vs /W={pw}",
            ))

        ref = atlas_glyphs.get(full_key)
        if not ref:
            continue

        checks = (
            ("raw_glyf_hash", "GLYPH_OUTLINE_MISMATCH"),
            ("outline_norm_hash", "GLYPH_OUTLINE_MISMATCH"),
            ("points_fingerprint", "GLYPH_OUTLINE_MISMATCH"),
            ("on_curve_fingerprint", "GLYPH_OUTLINE_MISMATCH"),
            ("instruction_bytecode_hash", "GLYPH_OUTLINE_MISMATCH"),
            ("hmtx_advanceWidth", "CMAP_W_MISMATCH"),
        )
        for field_name, code in checks:
            cur_val = cur.get(field_name)
            if not cur_val:
                continue
            if _atlas_allowed(ref, field_name, cur_val):
                continue
            # compile()/bytecode hashes drift across fontTools; empty atlas stubs
            # (historical failed extract) must not HARD. Geometry fingerprints win.
            if field_name in {
                "raw_glyf_hash",
                "outline_norm_hash",
                "instruction_bytecode_hash",
            }:
                if _atlas_allowed(ref, "points_fingerprint", cur.get("points_fingerprint")):
                    continue
                if _atlas_allowed(ref, "on_curve_fingerprint", cur.get("on_curve_fingerprint")):
                    continue
                outlines = ref.get("outline_norm_hash") or []
                if not isinstance(outlines, list):
                    outlines = [outlines] if outlines else []
                # sha1(b"")[:12] — empty compile stub
                if not outlines or all(o in ("", "da39a3ee5e6b") for o in outlines):
                    continue
                if not (ref.get("normalized_points") or ref.get("normalized_points_variants")):
                    continue
            if field_name == "hmtx_advanceWidth":
                ref_vals = ref.get("hmtx_advanceWidth", ref.get("hmtx_advance", []))
                if isinstance(ref_vals, list) and cur_val in ref_vals:
                    continue
            allowed = ref.get(field_name, [])
            res.flags.append(HardFlag(
                code,
                f"{font}: {ch!r} CID {cid} — {field_name}={cur_val!r} "
                f"вне атласа ({allowed[:2] if isinstance(allowed, list) else allowed})",
            ))
            break

        comps = cur.get("composite_components") or []
        if comps:
            ck = _json_key(comps)
            known = {_json_key(v) for v in ref.get("composite_components_variants", [])}
            if ref.get("composite_components"):
                known.add(_json_key(ref["composite_components"]))
            if known and ck not in known:
                res.flags.append(HardFlag(
                    "GLYPH_OUTLINE_MISMATCH",
                    f"{font}: {ch!r} CID {cid} — composite transform вне атласа",
                ))

    for rr in obs.get("render_runs", []):
        text = rr.get("text", "")
        if not text.strip() or len(text) > 80:
            continue
        delta = rr.get("width_delta")
        if delta is not None and delta > _RENDER_TOL_PT:
            render_mismatches += 1
            if render_mismatches <= 3:
                res.flags.append(HardFlag(
                    "TBANK_GLYPH_RENDER_GEOMETRY_MISMATCH",
                    f"{rr.get('font')}: «{text[:30]}» calc={rr.get('calc_width'):.3f} "
                    f"fitz={rr.get('fitz_width'):.3f} Δ={delta:.3f}pt",
                ))

    res.stats["render_mismatches"] = render_mismatches
    res.stats["hard_count"] = len(res.flags)
    return res


def check_tbank_glyph_atlas(pdf: bytes) -> AtlasResult:
    return validate_glyph_atlas(pdf, load_atlas())
