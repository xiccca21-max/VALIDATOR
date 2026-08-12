"""A-FONT-GLYPH-SLOT-TRANSPLANT-001 — glyph outline in wrong GID / hmtx mismatch."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

from .font_layers import _font_objects
from .glyf_fingerprint import _collect_used_by_font, _extract_fontfile2, _font_cid_maps
from .pdf_forensics import _glyph_outline_hash
from .tbank_jasper_profile import claims_confirmed_tbank_profile

RULE_ID = "A-FONT-GLYPH-SLOT-TRANSPLANT-001"
HARD_CODE = "GLYPH_SLOT_TRANSPLANT"
_CANON_PATH = Path(__file__).with_name("atlas_data") / "tbank_glyph_slot_canon.json"
_FONT_KEYS = ("F1", "F2")
_WHITESPACE = frozenset(" \t\r\n\u00a0\u202f")


@dataclass
class TransplantFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID


@dataclass
class TransplantResult:
    flags: list[TransplantFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _merged_cmap(pdf: bytes, font_key: str, fonts: dict) -> dict[int, str]:
    out = dict(_font_cid_maps(pdf).get(font_key, {}))
    for cid, ch in (fonts.get(font_key, {}).get("cmap") or {}).items():
        if ch:
            out[cid] = ch
    return out


def load_slot_canon() -> dict[str, Any]:
    if not _CANON_PATH.is_file():
        return {"version": "0", "fonts": {}}
    return json.loads(_CANON_PATH.read_text(encoding="utf-8"))


def _canon_by_cp(canon: dict[str, Any]) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {}
    for font_key, glyphs in (canon.get("fonts") or {}).items():
        mapped: dict[int, dict] = {}
        for hex_cp, entry in glyphs.items():
            mapped[int(hex_cp, 16)] = entry
        out[font_key] = mapped
    return out


def _gid_owner(canon_cp: dict[int, dict]) -> dict[int, int]:
    owners: dict[int, int] = {}
    for cp, entry in canon_cp.items():
        owners[int(entry["gid"])] = cp
    return owners


def _is_non_space(ch: str) -> bool:
    return bool(ch) and ch not in _WHITESPACE


def check_glyph_slot_transplant(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
    canon: dict[str, Any] | None = None,
) -> TransplantResult:
    out = TransplantResult()
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        out.stats["skipped"] = "profile_gate"
        return out
    if not TTFont:
        out.stats["skipped"] = "no_fonttools"
        return out

    canon = canon or load_slot_canon()
    by_cp = _canon_by_cp(canon)
    if not any(by_cp.values()):
        out.stats["skipped"] = "canon_missing"
        return out

    fonts, _ = _font_objects(pdf_bytes)
    used_by_font = _collect_used_by_font(pdf_bytes)
    checked = 0
    hits: list[dict[str, Any]] = []

    for font_key in _FONT_KEYS:
        canon_cp = by_cp.get(font_key, {})
        if not canon_cp:
            continue
        gid_owner = _gid_owner(canon_cp)
        outline_to_cp = {
            entry["outline_norm_hash"]: cp
            for cp, entry in canon_cp.items()
            if entry.get("outline_norm_hash")
        }
        ttf = _extract_fontfile2(pdf_bytes, font_key)
        if not ttf:
            continue
        try:
            tt = TTFont(BytesIO(ttf))
            order = tt.getGlyphOrder()
        except Exception:
            continue

        head = tt["head"]
        x0_lsb = bool(int(head.flags) & 0x02)
        cmap = _merged_cmap(pdf_bytes, font_key, fonts)

        w_dict: dict[int, int] = {}
        dw: int | None = None
        try:
            from .tbank_glyph_atlas import _font_w_and_dw
            w_dict, dw, _ = _font_w_and_dw(pdf_bytes, font_key)
        except Exception:
            pass

        for cid in sorted(used_by_font.get(font_key, ())):
            ch = cmap.get(cid, "")
            if not _is_non_space(ch):
                continue
            cp = ord(ch[0])
            ref = canon_cp.get(cp)
            if not ref:
                continue

            gid = cid
            if gid < 0 or gid >= len(order):
                continue
            gname = order[gid]
            g = tt["glyf"][gname]
            contours = int(getattr(g, "numberOfContours", 0) or 0)
            if contours == 0:
                continue
            try:
                g.expand(tt["glyf"])
            except Exception:
                pass

            outline = _glyph_outline_hash(ttf, gid) or ""
            if not outline:
                continue

            adv, lsb = tt["hmtx"][gname]
            adv, lsb = int(adv), int(lsb)
            x_min = int(g.xMin)
            x_max = int(g.xMax)
            pdf_w = w_dict.get(cid, dw)
            checked += 1

            canon_gid = int(ref["gid"])
            canon_outline = ref.get("outline_norm_hash", "")
            reasons: list[str] = []

            if outline == canon_outline and gid != canon_gid:
                reasons.append(
                    f"outline {ch!r} совпадает с каноном, но GID {gid} ≠ {canon_gid}"
                )

            if x0_lsb and lsb != x_min:
                reasons.append(f"head.flags x=0: LSB {lsb} ≠ glyph.xMin {x_min}")

            owner_cp = gid_owner.get(gid)
            if (
                outline == canon_outline
                and gid != canon_gid
                and owner_cp is not None
                and owner_cp != cp
            ):
                slot_ref = canon_cp.get(owner_cp, {})
                slot_adv = int(slot_ref.get("hmtx_advanceWidth", -1))
                slot_lsb = int(slot_ref.get("hmtx_lsb", -1))
                if lsb == slot_lsb and adv == slot_adv:
                    owner_ch = slot_ref.get("unicode", chr(owner_cp))
                    reasons.append(
                        f"outline {ch!r} в слоте GID {gid} ({owner_ch!r}): "
                        f"hmtx/adv={adv}, lsb={lsb} — метрики принимающего слота"
                    )
                if pdf_w is not None and slot_adv >= 0 and int(pdf_w) == slot_adv:
                    reasons.append(
                        f"/W={pdf_w} совпадает с каноном слота GID {gid}, не с {canon_gid}"
                    )

            if not reasons:
                continue

            detail = (
                f"{font_key}: {ch!r} (U+{cp:04X}) CID/GID {gid}; "
                + "; ".join(dict.fromkeys(reasons))
            )
            hits.append({
                "font": font_key,
                "unicode": ch,
                "cp": cp,
                "gid": gid,
                "canon_gid": canon_gid,
                "outline": outline[:16],
                "lsb": lsb,
                "xMin": x_min,
                "pdf_w": pdf_w,
                "reasons": reasons,
            })
            out.flags.append(TransplantFlag(HARD_CODE, detail, rule_id=RULE_ID))

    out.stats["checked"] = checked
    out.stats["hits"] = hits
    out.stats["canon_version"] = canon.get("version", "0")
    return out
