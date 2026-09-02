"""Used-CID, TrueType integrity, and GID-independent glyph geometry checks."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib import TTFont
except ImportError:
    DecomposingRecordingPen = None
    TTFont = None

try:
    import fitz
except ImportError:
    fitz = None

from .pdfutil import PdfObject, objects, resource_map
from .streams import (
    _exact_oracle_bi_profile,
    _object_count,
    _pdf_version,
    identify_emitter,
    stream_role,
)
from .types import ForensicResult

ATLAS_DIR = Path(__file__).with_name("atlas_data")
RULE_GROUP = "alfa_v2.fonts"
_TEXT_TOKEN_RE = re.compile(
    rb"/([^\s/<>\[\]()]+)\s+[-.\d]+\s+Tf|"
    rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>|\[(?:[^\[\]]|\((?:\\.|[^\\()])*\))*\])\s*(?:Tj|TJ|'|\")",
    re.S,
)


def _sfnt_table_tags(dec: bytes) -> tuple[str, ...]:
    """Return SFNT table directory tags in file order."""
    if not dec or len(dec) < 12 or dec[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
        return ()
    n = struct.unpack(">H", dec[4:6])[0]
    if n <= 0 or 12 + n * 16 > len(dec):
        return ()
    return tuple(
        dec[12 + i * 16 : 16 + i * 16].decode("latin1", "replace")
        for i in range(n)
    )


def _load_atlas() -> dict[str, Any]:
    try:
        data = json.loads((ATLAS_DIR / "glyph_atlas.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _string_bytes(token: bytes) -> bytes:
    if token.startswith(b"<"):
        try:
            return bytes.fromhex(re.sub(rb"\s+", b"", token[1:-1]).decode())
        except ValueError:
            return b""
    if token.startswith(b"("):
        inner = token[1:-1]
        inner = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 255]), inner)
        return re.sub(rb"\\([nrtbf()\\])", lambda m: m.group(1), inner)
    return b""


def _cids(token: bytes) -> list[int]:
    strings = re.findall(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>", token, re.S)
    raw = b"".join(_string_bytes(value) for value in strings)
    if len(raw) >= 2 and len(raw) % 2 == 0:
        return [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw), 2)]
    return list(raw)


def _used_cids(pdf_objects: dict[int, PdfObject]) -> dict[str, set[int]]:
    used: dict[str, set[int]] = {}
    for obj in pdf_objects.values():
        data = obj.decoded_stream or b""
        if b"BT" not in data:
            continue
        current = ""
        for match in _TEXT_TOKEN_RE.finditer(data):
            if match.group(1):
                current = match.group(1).decode("latin1")
            elif current and match.group(2):
                used.setdefault(current, set()).update(_cids(match.group(2)))
    return used


def _stream(pdf_objects: dict[int, PdfObject], number: int | None) -> bytes:
    return (pdf_objects.get(number).decoded_stream or b"") if number in pdf_objects else b""


def _tounicode(blob: bytes) -> dict[int, str]:
    """Parse ToUnicode CMap from beginbfchar / beginbfrange sections only.

    Scanning the whole stream for ``<a> <b> <c>`` falsely treats adjacent bfchar
    pairs as bfrange rows and invents thousands of synthetic CID mappings.
    """
    mapping: dict[int, str] = {}
    for block in re.finditer(rb"\d+\s+beginbfchar(.*?)endbfchar", blob or b"", re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block.group(1)):
            try:
                cid = int(src, 16)
                raw = bytes.fromhex(dst.decode())
                mapping[cid] = raw.decode("utf-16-be", "ignore")
            except (ValueError, UnicodeError):
                pass
    for block in re.finditer(rb"\d+\s+beginbfrange(.*?)endbfrange", blob or b"", re.S):
        body = block.group(1)
        for lo, hi, base in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", body
        ):
            try:
                start, stop, unicode_base = int(lo, 16), int(hi, 16), int(base, 16)
                for offset, cid in enumerate(range(start, stop + 1)):
                    mapping[cid] = chr(unicode_base + offset)
            except (ValueError, OverflowError):
                pass
        for lo, hi, arr in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]", body
        ):
            try:
                start, stop = int(lo, 16), int(hi, 16)
                values = re.findall(rb"<([0-9A-Fa-f]+)>", arr)
                for offset, cid in enumerate(range(start, stop + 1)):
                    if offset >= len(values):
                        break
                    raw = bytes.fromhex(values[offset].decode())
                    mapping[cid] = raw.decode("utf-16-be", "ignore")
            except (ValueError, UnicodeError, OverflowError):
                pass
    return mapping


def _printable_glyph_char(char: str) -> bool:
    """Letter-class printable ToUnicode (Latin/Cyrillic); excludes .notdef/space."""
    if not char or len(char) != 1 or char.isspace():
        return False
    return char.isalpha()


def _exact_oracle_font_profile(pdf: bytes, producer: str) -> bool:
    """Legacy 16-object Oracle shell gate (producer + PDF 1.6 + object count)."""
    if (producer or "").strip().lower() != "oracle bi publisher 12.2.1.4.0":
        return False
    if _pdf_version(pdf) != "1.6":
        return False
    return _object_count(pdf) == 16


def _oracle_role_counts(pdf: bytes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects(pdf).values():
        if obj.raw_stream is None or b"/FlateDecode" not in obj.dictionary:
            continue
        role = stream_role(obj)
        counts[role] = counts.get(role, 0) + 1
    return counts


def _oracle_static_assets_ok(pdf: bytes, producer: str) -> bool:
    """True when claimed Oracle stable images all match atlas (no partial drift)."""
    try:
        from .static_assets import check_static_assets
    except ImportError:
        return True
    assets = check_static_assets(pdf, producer=producer)
    expected = int(assets.stats.get("expected_asset_count") or 0)
    matched = int(assets.stats.get("matched_asset_count") or 0)
    if expected <= 0:
        # Atlas unavailable — do not block historical invariants solely on assets.
        return True
    if assets.stats.get("partial_replacement"):
        return False
    return matched == expected


def exact_oracle_profile(pdf: bytes, producer: str) -> bool:
    """Full ALFA_ORACLE_BIP_12_2_1_4 gate for historical HARD invariants.

    New Oracle generators / object graphs / assets must NOT inherit these
    historical constants as automatic FAKE.
    """
    roles = _oracle_role_counts(pdf)
    if not _exact_oracle_bi_profile(pdf, producer, roles):
        return False
    if not _oracle_static_assets_ok(pdf, producer):
        return False
    return True


def _parse_font_bbox(descriptor: PdfObject | None) -> list[float] | None:
    if not descriptor:
        return None
    match = re.search(
        rb"/FontBBox\s*\[\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
        rb"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\]",
        descriptor.dictionary or b"",
    )
    if not match:
        return None
    return [float(match.group(i)) for i in range(1, 5)]


def _head_expected_bbox(tt: Any) -> list[float]:
    head = tt["head"]
    upem = float(head.unitsPerEm or 1000)
    return [
        head.xMin * 1000.0 / upem,
        head.yMin * 1000.0 / upem,
        head.xMax * 1000.0 / upem,
        head.yMax * 1000.0 / upem,
    ]


def _atlas_metrics(reference: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not isinstance(reference, dict):
        return None, None
    adv = reference.get("advance_width")
    if adv is None:
        widths = reference.get("advance_widths")
        if isinstance(widths, list) and len(widths) == 1:
            adv = widths[0]
    lsb = reference.get("lsb")
    if lsb is None:
        lsbs = reference.get("lsbs")
        if isinstance(lsbs, list) and len(lsbs) == 1:
            lsb = lsbs[0]
    try:
        return (int(adv) if adv is not None else None,
                int(lsb) if lsb is not None else None)
    except (TypeError, ValueError):
        return None, None


def _cid_fully_embedded(
    cid: int,
    *,
    descendant: PdfObject,
    widths: dict[int, int],
    cid_map: bytes,
    tt: Any,
) -> bool:
    """True when unused CID is present across ToUnicode→/W→GID→loca/glyf→hmtx."""
    if cid not in widths:
        return False
    gid = _gid(cid, descendant, cid_map)
    if gid is None:
        return False
    order = tt.getGlyphOrder()
    if gid < 0 or gid >= len(order):
        return False
    gname = order[gid]
    try:
        glyph = tt["glyf"][gname]
        _advance, _lsb = tt["hmtx"][gname]
    except Exception:
        return False
    empty = glyph.numberOfContours == 0 and not glyph.isComposite()
    return not empty


def _widths(blob: bytes) -> tuple[dict[int, int], int]:
    widths: dict[int, int] = {}
    dw_match = re.search(rb"/DW\s+(\d+)", blob)
    default = int(dw_match.group(1)) if dw_match else 1000
    match = re.search(rb"/W\s*\[(.*?)\]\s*(?:/|>>)", blob, re.S)
    if not match:
        return widths, default
    value = match.group(1)
    for first, array in re.findall(rb"(\d+)\s*\[([^\]]*)\]", value):
        start = int(first)
        for offset, width in enumerate(re.findall(rb"-?\d+", array)):
            widths[start + offset] = int(width)
    ranges_removed = re.sub(rb"\d+\s*\[[^\]]*\]", b" ", value)
    for first, last, width in re.findall(rb"(\d+)\s+(\d+)\s+(-?\d+)", ranges_removed):
        for cid in range(int(first), int(last) + 1):
            widths[cid] = int(width)
    return widths, default


def _font_parts(
    font_obj: PdfObject, pdf_objects: dict[int, PdfObject]
) -> tuple[PdfObject, dict[int, str], dict[int, int], int, bytes, bytes]:
    descendant_match = re.search(rb"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", font_obj.dictionary)
    descendant = pdf_objects.get(int(descendant_match.group(1))) if descendant_match else font_obj
    descendant = descendant or font_obj
    tu_match = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", font_obj.dictionary)
    cmap = _tounicode(_stream(pdf_objects, int(tu_match.group(1)) if tu_match else None))
    widths, default_width = _widths(descendant.dictionary)
    cid_map = b""
    cid_match = re.search(rb"/CIDToGIDMap\s+(\d+)\s+0\s+R", descendant.dictionary)
    if cid_match:
        cid_map = _stream(pdf_objects, int(cid_match.group(1)))
    descriptor_match = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", descendant.dictionary)
    descriptor = pdf_objects.get(int(descriptor_match.group(1))) if descriptor_match else None
    ff2 = b""
    if descriptor:
        ff2_match = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", descriptor.dictionary)
        ff2 = _stream(pdf_objects, int(ff2_match.group(1)) if ff2_match else None)
    return descendant, cmap, widths, default_width, cid_map, ff2


def _gid(cid: int, descendant: PdfObject, cid_map: bytes) -> int | None:
    if b"/CIDToGIDMap /Identity" in descendant.dictionary or not cid_map:
        return cid
    offset = cid * 2
    return int.from_bytes(cid_map[offset:offset + 2], "big") if offset + 2 <= len(cid_map) else None



def _stable_text_char(char: str) -> bool:
    """True for real alphabetic ToUnicode, not Oracle synthetic slots/digits."""
    if not char or len(char) != 1:
        return False
    # Digits/punctuation are reused across Oracle subset encodings and must not
    # drive HARD transplant verdicts.
    if ("A" <= char <= "Z") or ("a" <= char <= "z"):
        return True
    if ("А" <= char <= "я") or char in "Ёё":
        return True
    return False

def _outline(tt: Any, gid: int) -> tuple[str, tuple[int, int, int, int] | None]:
    """GID-independent outline hash; must match build_alfa_v2_atlas._canonical_geometry."""
    if DecomposingRecordingPen is None:
        return "", None
    order = tt.getGlyphOrder()
    if gid < 0 or gid >= len(order):
        return "", None
    glyph_set = tt.getGlyphSet()
    pen = DecomposingRecordingPen(glyph_set)
    try:
        glyph_set[order[gid]].draw(pen)
    except Exception:
        return "", None
    upem = float(tt["head"].unitsPerEm or 1000)
    commands: list[list[Any]] = []
    coords: list[tuple[float, float]] = []
    for operator, operands in pen.value:
        normalized = []
        for operand in operands:
            if isinstance(operand, tuple):
                point = tuple(round(float(v) / upem, 6) for v in operand)
                normalized.append(list(point))
                if len(point) >= 2:
                    coords.append((point[0], point[1]))
            else:
                normalized.append(operand)
        commands.append([operator, normalized])
    digest = hashlib.sha256(
        (
            json.dumps(
                commands,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    bbox = None
    if coords:
        xs, ys = [p[0] for p in coords], [p[1] for p in coords]
        bbox = (
            round(min(xs) * 1_000_000),
            round(min(ys) * 1_000_000),
            round(max(xs) * 1_000_000),
            round(max(ys) * 1_000_000),
        )
    return digest, bbox


def _composite_closure(tt: Any, roots: set[int]) -> tuple[set[int], set[int]]:
    order = tt.getGlyphOrder()
    closure, missing = set(roots), set()
    stack = list(roots)
    while stack:
        gid = stack.pop()
        if gid < 0 or gid >= len(order):
            missing.add(gid)
            continue
        glyph = tt["glyf"][order[gid]]
        if not glyph.isComposite():
            continue
        for component in glyph.components:
            try:
                child = order.index(component.glyphName)
            except ValueError:
                missing.add(-1)
                continue
            if child not in closure:
                closure.add(child)
                stack.append(child)
    return closure, missing


def _atlas_glyphs(atlas: dict[str, Any], emitter: str) -> dict[str, Any]:
    scoped = atlas.get(emitter, atlas)
    return scoped.get("glyphs", {}) if isinstance(scoped, dict) else {}


def check_fonts(pdf: bytes, *, producer: str = "") -> ForensicResult:
    result = ForensicResult()
    pdf_objects = objects(pdf)
    resources = resource_map(pdf, b"Font")
    used = _used_cids(pdf_objects)
    emitter = identify_emitter(pdf, producer)
    atlas = _load_atlas()
    glyph_atlas = _atlas_glyphs(atlas, emitter)
    known_ff2 = set(atlas.get(emitter, {}).get("fontfile2_sha256", [])) if isinstance(atlas.get(emitter), dict) else set()
    subset_prefixes: list[str] = []
    observations: list[dict[str, Any]] = []

    # Oracle SBP Tahoma pack (decoded ≥20570, n=14): unique positive hmtx
    # advances are 42–45. SEQ CLEAN-miss alfa_sbp_114100 keeps hinting/csum
    # but drops the width vocabulary to 41. Card Oracle packs (16300/16792)
    # sit at 30–32 and must stay outside this floor.
    _ORACLE_SBP_FF2_MIN = 20_570
    _ORACLE_SBP_HMTX_UNIQ_MIN = 42

    # Exact FontFile2 decoded sizes (чеки). Envelope let SEQ slip; exact set
    # is observational only (ALFA_FONTFILE2_SIZE_EXACT_UNKNOWN is IGNORE).
    # 16300/16792 removed — SEQ rebuilds without hinting (PADD+glyf…), not live
    # Oracle Tahoma. 19654 = Oracle phone subset (intrabank, live cvt/fpgm/prep);
    # SBP packs stay ≥20570. 21370 is a live Oracle SBP pack in the old
    # 21132–21682 hole — ALFA_ORACLE_FF2_SIZE_MIDGAP was dropped (FP on genuines).
    _ORACLE_FF2_EXACT = frozenset({
        19654, 20570, 20850, 20882, 20944, 21058, 21132, 21370, 21682, 21808,
        22248, 22356, 22582,
    })
    _QUARTZ_FF2_EXACT = frozenset({
        11880, 19830, 19946, 20076, 20170, 20378, 20458, 20514, 20594, 20620,
        20642, 20706, 20848, 21048, 21068, 21112, 21282, 21486, 21518, 21662,
        22088, 22096, 22748, 22880, 22954, 54292,
    })

    # Oracle BI genuines: FontFile2 decoded ∈ [20570, 22582] (clean n=14).
    # Oversize SEQ (22768+) kept diagnostic (corpus may grow).
    # Undersize is not future growth — SEQ rebuilds land ~15228–16300.
    ff2_decs: list[int] = []
    ff2_blobs: list[bytes] = []
    for m in re.finditer(rb"/FontFile2\s+(\d+)\s+\d+\s+R", pdf):
        onum = int(m.group(1))
        obj = pdf_objects.get(onum)
        if not obj or obj.decoded_stream is None:
            continue
        ff2_decs.append(len(obj.decoded_stream))
        ff2_blobs.append(obj.decoded_stream)
    if ff2_decs:
        result.stats["fontfile2_decoded_sizes"] = ff2_decs
    if emitter == "oracle" and ff2_decs:
        atlas_min = 20_570
        atlas_max = 22_582
        hard_lo = atlas_min  # exact corpus floor; no slack
        hard_hi = atlas_max + 100  # 22682; SEQ min observed 22768
        mx = max(ff2_decs)
        mn = min(ff2_decs)
        result.stats["fontfile2_envelope"] = {
            "atlas_min": atlas_min,
            "atlas_max": atlas_max,
            "hard_lo": hard_lo,
            "hard_hi": hard_hi,
        }
        if mx > hard_hi:
            result.add(
                "ALFA_FONTFILE2_SIZE_STRONG_OUTLIER",
                (
                    f"FontFile2 decoded {mx} B — сильно больше эталона Oracle BI "
                    f"(atlas≤{atlas_max}, n=14; HARD>{hard_hi})"
                ),
                group=RULE_GROUP,
                evidence={"fontfile2_decoded_max": mx, "atlas_max": atlas_max},
            )

        # Oracle Tahoma always ships cvt/fpgm/prep. SEQ fontTools rebuilds drop
        # hinting and inject a leading PADD table (alfa_sbp_115437 CLEAN-miss).
        rebuild_shell = False
        for blob in ff2_blobs:
            tags = _sfnt_table_tags(blob)
            if not tags:
                continue
            result.stats.setdefault("sfnt_table_orders", []).append(list(tags))
            has_padd = "PADD" in tags
            missing_hint = [t for t in ("cvt ", "fpgm", "prep") if t not in tags]
            if has_padd or missing_hint:
                rebuild_shell = True
                result.add(
                    "ALFA_ORACLE_SFNT_HINTING_TABLES_MISSING",
                    (
                        f"Oracle FontFile2 SFNT order={list(tags)} — "
                        f"{'PADD-rebuild; ' if has_padd else ''}"
                        f"нет hinting-таблиц {missing_hint or '—'}; "
                        f"корпус Oracle BI всегда cvt/fpgm/…/prep (n=14)"
                    ),
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence={
                        "sfnt_order": list(tags),
                        "has_padd": has_padd,
                        "missing_hint": missing_hint,
                    },
                )
                break

        # Undersize alone FP on Oracle card→card genuines (16300/16792 with
        # live hinting). Keep HARD only together with rebuild shell (PADD /
        # missing cvt|fpgm|prep) — SBP SEQ kits.
        if mn < hard_lo and rebuild_shell:
            result.add(
                "ALFA_FONTFILE2_SIZE_UNDERSIZE",
                (
                    f"FontFile2 decoded {mn} B — меньше эталона Oracle BI "
                    f"(atlas {atlas_min}–{atlas_max}, n=14; HARD<{hard_lo}) "
                    f"при PADD/no-hinting rebuild"
                ),
                group=RULE_GROUP,
                evidence={
                    "fontfile2_decoded_min": mn,
                    "atlas_min": atlas_min,
                    "atlas_max": atlas_max,
                    "rebuild_shell": True,
                },
            )

    if emitter in {"oracle", "quartz"} and ff2_decs:
        exact_ff2 = _ORACLE_FF2_EXACT if emitter == "oracle" else _QUARTZ_FF2_EXACT
        label = "Oracle BI" if emitter == "oracle" else "Quartz/iOS"
        unknown = sorted({sz for sz in ff2_decs if sz not in exact_ff2})
        result.stats["fontfile2_exact_atlas"] = {
            "emitter": emitter,
            "sizes": ff2_decs,
            "allowed_n": len(exact_ff2),
            "unknown": unknown,
        }
        if unknown:
            result.add(
                "ALFA_FONTFILE2_SIZE_EXACT_UNKNOWN",
                (
                    f"FontFile2 decoded {unknown} B вне точного корпуса "
                    f"{label} (allowed={sorted(exact_ff2)}, n={len(exact_ff2)}) — "
                    f"SEQ subset в зазоре envelope"
                ),
                group=RULE_GROUP,
                evidence={"unknown_sizes": unknown, "emitter": emitter},
            )

    # Full exact Oracle BI 12.2.1.4 profile — historical HARD invariants apply only here.
    oracle_profile = exact_oracle_profile(pdf, producer)
    oracle_font_profile = _exact_oracle_font_profile(pdf, producer)
    result.stats["exact_oracle_profile"] = oracle_profile
    result.stats["exact_oracle_font_profile"] = oracle_font_profile

    report_head: dict[str, Any] = {}
    conflicting_glyphs: list[dict[str, Any]] = []
    extra_printable_glyphs: list[dict[str, Any]] = []

    # Exact Oracle BI subset closure: cmap CIDs must equal used Tj/TJ CIDs (+ CID 0).
    if oracle_profile or oracle_font_profile:
        closure_reports: list[dict[str, Any]] = []
        decisive_hits: list[dict[str, Any]] = []
        for font_name, font_num in resources.items():
            font_obj = pdf_objects.get(font_num)
            if not font_obj:
                continue
            descendant, cmap, widths, _default_width, cid_map, ff2 = _font_parts(
                font_obj, pdf_objects
            )
            used_cids = set(used.get(font_name, set()))
            cmap_cids = set(cmap)
            unexpected_cids = sorted(cmap_cids - used_cids - {0})
            unexpected_unicode = [
                cmap[cid] for cid in unexpected_cids if cmap.get(cid)
            ]
            embedded_surplus: list[dict[str, Any]] = []
            if ff2 and unexpected_cids and TTFont is not None:
                try:
                    tt = TTFont(BytesIO(ff2), lazy=False)
                except Exception:
                    tt = None
                if tt is not None:
                    for cid in unexpected_cids:
                        char = cmap.get(cid, "")
                        if not _printable_glyph_char(char):
                            continue
                        if not _cid_fully_embedded(
                            cid,
                            descendant=descendant,
                            widths=widths,
                            cid_map=cid_map,
                            tt=tt,
                        ):
                            continue
                        embedded_surplus.append(
                            {
                                "cid": cid,
                                "unicode": char,
                                "gid": _gid(cid, descendant, cid_map),
                                "width": widths.get(cid),
                            }
                        )
            report = {
                "font": font_name,
                "used_cids": sorted(used_cids),
                "cmap_cids": sorted(cmap_cids),
                "unexpected_cids": unexpected_cids,
                "unexpected_unicode": unexpected_unicode,
                "embedded_surplus": embedded_surplus,
            }
            closure_reports.append(report)
            if embedded_surplus:
                decisive_hits.append(report)
                extra_printable_glyphs.extend(embedded_surplus)
        result.stats["oracle_subset_closure"] = closure_reports
        result.stats.update(
            used_cids={hit["font"]: hit["used_cids"] for hit in closure_reports},
            cmap_cids={hit["font"]: hit["cmap_cids"] for hit in closure_reports},
            unexpected_cids={
                hit["font"]: hit["unexpected_cids"] for hit in closure_reports
            },
            unexpected_unicode={
                hit["font"]: hit["unexpected_unicode"] for hit in closure_reports
            },
        )
        if decisive_hits and oracle_profile:
            surplus_chars = "".join(
                item["unicode"]
                for hit in decisive_hits
                for item in hit["embedded_surplus"]
            )
            result.add(
                "ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION",
                "Oracle BI font subset embeds unused printable glyphs "
                f"{surplus_chars!r} present in ToUnicode /W /glyf /hmtx but absent "
                "from all Tj/TJ operators",
                tier="KNOWN",
                group=RULE_GROUP,
                evidence={
                    "fonts": decisive_hits,
                    "used_cids": {
                        hit["font"]: hit["used_cids"] for hit in decisive_hits
                    },
                    "cmap_cids": {
                        hit["font"]: hit["cmap_cids"] for hit in decisive_hits
                    },
                    "unexpected_cids": {
                        hit["font"]: hit["unexpected_cids"] for hit in decisive_hits
                    },
                    "unexpected_unicode": {
                        hit["font"]: hit["unexpected_unicode"] for hit in decisive_hits
                    },
                },
            )
            result.stats["decisive_flag"] = "ALFA_ORACLE_FONT_SUBSET_CLOSURE_VIOLATION"

    for font_name, cids in used.items():
        font_obj = pdf_objects.get(resources.get(font_name, -1))
        if not font_obj:
            result.add("ALFA_FONT_TABLE_INTEGRITY_VIOLATION", f"/{font_name} has no resolvable font object", group=RULE_GROUP)
            continue
        base = re.search(rb"/BaseFont\s*/([^\s/<>\[\]()]+)", font_obj.dictionary)
        if base:
            subset_prefixes.append(base.group(1).decode("latin1").split("+", 1)[0])
        descendant, cmap, widths, default_width, cid_map, ff2 = _font_parts(font_obj, pdf_objects)
        missing_unicode = sorted(cid for cid in cids if cid not in cmap or not cmap[cid])
        if missing_unicode:
            result.add(
                "ALFA_BROKEN_UNICODE_MAPPING",
                f"/{font_name} used CIDs lack ToUnicode mappings",
                group=RULE_GROUP,
                evidence={"cids": missing_unicode},
            )
        gids = {cid: _gid(cid, descendant, cid_map) for cid in cids}
        if any(gid is None for gid in gids.values()):
            result.add(
                "ALFA_FONT_CID_CLOSURE_VIOLATION",
                f"/{font_name} CIDToGIDMap does not cover all used CIDs",
                group=RULE_GROUP,
            )
        if not ff2:
            result.add("ALFA_FONT_TABLE_INTEGRITY_VIOLATION", f"/{font_name} has no decoded FontFile2", group=RULE_GROUP)
            continue
        length1_match = None
        desc_match = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", descendant.dictionary)
        desc_obj = pdf_objects.get(int(desc_match.group(1))) if desc_match else None
        ff2_obj = None
        if desc_obj:
            ff2_ref = re.search(rb"/FontFile2\s+(\d+)\s+0\s+R", desc_obj.dictionary)
            if ff2_ref:
                ff2_obj = pdf_objects.get(int(ff2_ref.group(1)))
        for blob in (
            (ff2_obj.dictionary if ff2_obj else b""),
            (desc_obj.dictionary if desc_obj else b""),
            descendant.dictionary,
        ):
            length1_match = re.search(rb"/Length1\s+(\d+)", blob or b"")
            if length1_match:
                break
        if length1_match and int(length1_match.group(1)) != len(ff2):
            result.add(
                "ALFA_FONTFILE2_LENGTH1_MISMATCH",
                f"/{font_name} /Length1={int(length1_match.group(1))} but decoded "
                f"FontFile2 length is {len(ff2)}",
                group=RULE_GROUP,
                evidence={
                    "length1": int(length1_match.group(1)),
                    "decoded_length": len(ff2),
                },
            )
        ff2_sha = hashlib.sha256(ff2).hexdigest()
        if known_ff2 and ff2_sha not in known_ff2:
            result.add(
                "ALFA_NEW_FONTFILE2_SHA",
                f"/{font_name} FontFile2 SHA-256 is new",
                tier="DIAGNOSTIC",
                group=RULE_GROUP,
                evidence={"sha256": ff2_sha},
            )
        if TTFont is None:
            result.stats["fonttools_unavailable"] = True
            continue
        try:
            tt = TTFont(BytesIO(ff2), lazy=False)
            required = {"loca", "glyf", "hmtx", "head", "maxp", "hhea"}
            missing_tables = sorted(required - set(tt.keys()))
            if missing_tables:
                raise ValueError(f"missing tables: {missing_tables}")
            order = tt.getGlyphOrder()
            num_glyphs = int(tt["maxp"].numGlyphs)
            metric_count = int(tt["hhea"].numberOfHMetrics)
            if num_glyphs != len(order) or metric_count <= 0 or metric_count > num_glyphs:
                raise ValueError(
                    f"maxp/order/hhea mismatch: {num_glyphs}/{len(order)}/{metric_count}"
                )
            upem = int(tt["head"].unitsPerEm)
            if not 16 <= upem <= 16384:
                raise ValueError(f"impossible unitsPerEm={upem}")
        except Exception as exc:
            result.add(
                "ALFA_FONT_TABLE_INTEGRITY_VIOLATION",
                f"/{font_name} invalid loca/glyf/hmtx/head/maxp/hhea: {exc}",
                group=RULE_GROUP,
            )
            continue

        head = tt["head"]
        pdf_bbox = _parse_font_bbox(desc_obj)
        calculated_bbox = _head_expected_bbox(tt)
        report_head = {
            "font": font_name,
            "flags": int(head.flags),
            "indexToLocFormat": int(head.indexToLocFormat),
            "unitsPerEm": upem,
            "pdf_bbox": pdf_bbox,
            "calculated_bbox": [round(v, 4) for v in calculated_bbox],
        }
        result.stats.setdefault("ttf_head", {})[font_name] = report_head

        pos_adv = {
            int(advance)
            for advance, _lsb in tt["hmtx"].metrics.values()
            if int(advance) > 0
        }
        uniq_adv = len(pos_adv)
        result.stats.setdefault("hmtx_uniq_advances", []).append(uniq_adv)
        if (
            emitter == "oracle"
            and len(ff2) >= _ORACLE_SBP_FF2_MIN
            and uniq_adv < _ORACLE_SBP_HMTX_UNIQ_MIN
        ):
            result.add(
                "ALFA_ORACLE_SBP_HMTX_UNIQ_ADVANCES",
                (
                    f"/{font_name} unique positive hmtx advances={uniq_adv} "
                    f"< {_ORACLE_SBP_HMTX_UNIQ_MIN} при FontFile2={len(ff2)} B "
                    f"(Oracle SBP Tahoma n=14: 42–45) — пересобранный width "
                    f"vocabulary, не короче ФИО"
                ),
                tier="HARD",
                group=RULE_GROUP,
                evidence={
                    "hmtx_uniq_advances": uniq_adv,
                    "ff2_decoded": len(ff2),
                    "floor": _ORACLE_SBP_HMTX_UNIQ_MIN,
                },
            )

        if oracle_profile:
            if int(head.flags) != 27 or int(head.indexToLocFormat) != 1:
                result.add(
                    "ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT",
                    f"/{font_name} Oracle TTF head.flags={head.flags} "
                    f"indexToLocFormat={head.indexToLocFormat} "
                    f"(expected flags=27, indexToLocFormat=1)",
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence=report_head,
                )
            # Oracle BI keeps source Tahoma checkSumAdjustment across all
            # genuine subsets (n=16: always 1757709444). fontTools rebuilds
            # recalculate it (SEQ SBP CLEAN-miss → 1553904336).
            _ORACLE_CHECKSUM_ADJ = 1_757_709_444
            csum = int(head.checkSumAdjustment)
            report_head["checkSumAdjustment"] = csum
            if csum != _ORACLE_CHECKSUM_ADJ:
                result.add(
                    "ALFA_ORACLE_TTF_HEAD_MECHANICS_CONFLICT",
                    (
                        f"/{font_name} Oracle TTF head.checkSumAdjustment="
                        f"{csum} (expected {_ORACLE_CHECKSUM_ADJ}; "
                        f"корпус Oracle BI n=16 — SEQ subset rebuild)"
                    ),
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence=report_head,
                )
            if pdf_bbox is not None and any(
                abs(pdf_bbox[i] - calculated_bbox[i]) > 1.0 for i in range(4)
            ):
                result.add(
                    "ALFA_FONT_DESCRIPTOR_HEAD_BBOX_CONFLICT",
                    f"/{font_name} /FontBBox {pdf_bbox} ≠ head-derived "
                    f"{[round(v, 2) for v in calculated_bbox]}",
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence={
                        "pdf_bbox": pdf_bbox,
                        "calculated_bbox": calculated_bbox,
                    },
                )

        valid_roots = {gid for gid in gids.values() if gid is not None}
        closure, missing_components = _composite_closure(tt, valid_roots)
        if missing_components:
            result.add(
                "ALFA_FONT_CID_CLOSURE_VIOLATION",
                f"/{font_name} composite closure references missing glyphs",
                group=RULE_GROUP,
                evidence={"missing": sorted(missing_components)},
            )
        current_hash_to_chars: dict[str, list[str]] = {}
        for cid, gid in gids.items():
            if gid is None or gid >= len(order):
                result.add(
                    "ALFA_FONT_CID_CLOSURE_VIOLATION",
                    f"/{font_name} CID {cid} resolves outside maxp.numGlyphs",
                    group=RULE_GROUP,
                )
                continue
            glyph = tt["glyf"][order[gid]]
            char = cmap.get(cid, "")
            outline_hash, bbox = _outline(tt, gid)
            current_hash_to_chars.setdefault(outline_hash, []).append(char)
            advance, lsb = tt["hmtx"][order[gid]]
            pdf_width = widths.get(cid, default_width)
            scaled_advance = (float(advance) * 1000.0) / float(upem or 1000)
            empty = glyph.numberOfContours == 0 and not glyph.isComposite()
            if empty and char.strip():
                result.add(
                    "ALFA_USED_CID_EMPTY_GLYPH",
                    f"/{font_name} used CID {cid} ({char!r}) resolves to an empty glyph",
                    group=RULE_GROUP,
                    evidence={"cid": cid, "gid": gid},
                )
            if cid in widths and abs(scaled_advance - float(pdf_width)) > 2.0:
                result.add(
                    "ALFA_FONT_CID_CLOSURE_VIOLATION",
                    f"/{font_name} CID {cid} /W={pdf_width} differs from hmtx={advance} (scaled={scaled_advance:.1f})",
                    group=RULE_GROUP,
                )
            reference = glyph_atlas.get(char) or glyph_atlas.get(f"{ord(char):04X}" if char else "")
            allowed = reference.get("outline_hashes", reference.get("outline_hash", [])) if isinstance(reference, dict) else []
            allowed_set = {allowed} if isinstance(allowed, str) else set(allowed or [])
            # Unknown Unicode not in atlas → never FAKE by itself.
            if (
                oracle_profile
                and allowed_set
                and outline_hash
                and outline_hash not in allowed_set
                and _stable_text_char(char)
            ):
                conflicting_glyphs.append(
                    {
                        "cid": cid,
                        "unicode": char,
                        "kind": "outline",
                        "outline_hash": outline_hash,
                        "advance": int(advance),
                        "lsb": int(lsb),
                    }
                )
                result.add(
                    "ALFA_USED_GLYPH_OUTLINE_ATLAS_CONFLICT",
                    f"/{font_name} used CID {cid} ({char!r}) outline ≠ confirmed Tahoma atlas",
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence={
                        "cid": cid,
                        "unicode": char,
                        "gid": gid,
                        "outline_hash": outline_hash,
                    },
                )
            elif allowed_set and outline_hash not in allowed_set and _stable_text_char(char):
                transplanted_from = [
                    key for key, value in glyph_atlas.items()
                    if key != char and _stable_text_char(key) and outline_hash in (
                        {value.get("outline_hash")} if isinstance(value, dict) and isinstance(value.get("outline_hash"), str)
                        else set(value.get("outline_hashes", [])) if isinstance(value, dict) else set()
                    )
                ]
                result.add(
                    "ALFA_GLYPH_OUTLINE_MISMATCH" if not transplanted_from else "ALFA_GLYPH_SLOT_TRANSPLANT",
                    f"/{font_name} CID {cid} outline differs from unicode-keyed atlas",
                    tier="DIAGNOSTIC",
                    group=RULE_GROUP,
                    evidence={"unicode": char, "gid": gid, "outline_hash": outline_hash, "matches": transplanted_from},
                )

            exp_adv, exp_lsb = _atlas_metrics(reference if isinstance(reference, dict) else None)
            if (
                oracle_profile
                and exp_adv is not None
                and exp_lsb is not None
                and _stable_text_char(char)
                and (int(advance) != exp_adv or int(lsb) != exp_lsb)
            ):
                conflicting_glyphs.append(
                    {
                        "cid": cid,
                        "unicode": char,
                        "kind": "metric",
                        "advance": int(advance),
                        "lsb": int(lsb),
                        "expected_advance": exp_adv,
                        "expected_lsb": exp_lsb,
                    }
                )
                result.add(
                    "ALFA_USED_GLYPH_METRIC_CONFLICT",
                    f"/{font_name} used CID {cid} ({char!r}) hmtx "
                    f"advance={advance} lsb={lsb} ≠ atlas "
                    f"advance={exp_adv} lsb={exp_lsb}",
                    tier="HARD",
                    group=RULE_GROUP,
                    evidence={
                        "cid": cid,
                        "unicode": char,
                        "advance": int(advance),
                        "lsb": int(lsb),
                        "expected_advance": exp_adv,
                        "expected_lsb": exp_lsb,
                    },
                )

            observations.append(
                {
                    "font": font_name,
                    "cid": cid,
                    "unicode": char,
                    "gid": gid,
                    "outline_hash": outline_hash,
                    "bbox": bbox,
                    "advance": int(advance),
                    "lsb": int(lsb),
                }
            )
        for outline_hash, chars in current_hash_to_chars.items():
            stable = sorted({c for c in chars if _stable_text_char(c)})
            if len(stable) >= 2:
                result.add(
                    "ALFA_GLYPH_SLOT_TRANSPLANT",
                    f"/{font_name} outline reused for distinct ToUnicode chars {stable}",
                    tier="DIAGNOSTIC",
                    group=RULE_GROUP,
                    evidence={"outline_hash": outline_hash, "unicodes": stable},
                )
        result.stats.setdefault("composite_closure", {})[font_name] = sorted(closure)

    known_prefixes = set(atlas.get(emitter, {}).get("subset_prefixes", [])) if isinstance(atlas.get(emitter), dict) else set()
    for prefix in subset_prefixes:
        if known_prefixes and prefix not in known_prefixes:
            result.add(
                "ALFA_NEW_SUBSET_PREFIX",
                f"Font subset prefix {prefix!r} is new",
                tier="DIAGNOSTIC",
                group=RULE_GROUP,
            )
    if fitz is not None and observations:
        try:
            with fitz.open(stream=pdf, filetype="pdf") as doc:
                rendered = "".join(page.get_text("text") for page in doc)
            mapped = "".join(item["unicode"] for item in observations if item["unicode"])
            meaningful = re.sub(r"\W+", "", mapped)
            if meaningful and rendered and not any(token in rendered for token in re.findall(r"\w{4,}", meaningful)):
                result.add(
                    "ALFA_TEXT_RENDER_PARITY_MISMATCH",
                    "Used-CID ToUnicode text has no parity with PyMuPDF rendered extraction",
                    tier="DIAGNOSTIC",
                    group=RULE_GROUP,
                )
        except Exception:
            result.stats["render_parity_unavailable"] = True
    result.stats.update(
        emitter=emitter,
        used_cids={font: sorted(cids) for font, cids in used.items()},
        glyph_observations=observations,
        conflicting_glyphs=conflicting_glyphs,
        extra_printable_glyphs=extra_printable_glyphs,
        ttf_head_report=report_head,
    )
    return result


check_font_integrity = check_fonts
