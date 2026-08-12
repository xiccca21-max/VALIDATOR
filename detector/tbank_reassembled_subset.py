"""K-TBANK-REASSEMBLED-SUBSET-001 — known generator reassembly provenance (v1 + v2)."""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from .font_layers import _font_objects
from .glyf_fingerprint import _collect_used_by_font, _extract_fontfile2
from .reputation import check_known_fake
from .structure import content_skeleton_hash, content_stream_bytes
from .tbank_flate_profile import _OBJ_BODY_RE, _indirect_lengths, _length_from_hdr
from .tbank_glyph_atlas import (
    extract_glyph_observations,
    load_atlas,
    subset_builder_fingerprint,
)
from .tbank_jasper_profile import claims_confirmed_tbank_profile

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None  # type: ignore


RULE_ID = "K-TBANK-REASSEMBLED-SUBSET-001"
CODE = "TBANK_REASSEMBLED_BANK_ASSETS"
CODE_V2 = "TBANK_REASSEMBLED_BANK_ASSETS_V2"
_DATA_PATH = Path(__file__).with_name("atlas_data") / "tbank_reassembled_subset.json"

_TARGET_RIGHT_PT = 250.0
_RESIDUAL_QUANT = 0.05
_SUBJECT_MARKER = "/reports/IB/Receipt"


@dataclass
class ReassembledFlag:
    code: str
    detail: str
    rule_id: str = RULE_ID
    tier: str = "KNOWN"


@dataclass
class ReassembledResult:
    flags: list[ReassembledFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _load_data() -> dict:
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sha_json(obj: object) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pdf_meta(pdf_bytes: bytes) -> dict[str, str]:
    if not fitz:
        return {}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = dict(doc.metadata or {})
        doc.close()
        return {str(k): str(v or "") for k, v in meta.items()}
    except Exception:
        return {}


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text or ""
    except Exception:
        return ""


def _detect_channel(text: str) -> str:
    low = (text or "").lower()
    if "сбп" in low or "системы быстрых платежей" in low:
        return "sbp"
    if "телефон" in low:
        return "phone"
    if "карт" in low:
        return "card"
    if "клиенту т" in low or "клиенту тиньк" in low:
        return "internal"
    return "other"


# ── Shared feature extractors ─────────────────────────────────────────────────


def assembly_features(pdf_bytes: bytes) -> dict:
    """Normalized content-AST/font closure tuple used for corpus membership."""
    fonts, _ = _font_objects(pdf_bytes)
    used = _collect_used_by_font(pdf_bytes)
    text = _pdf_text(pdf_bytes)
    out: dict = {
        "channel": _detect_channel(text),
        "content_ast": content_skeleton_hash(pdf_bytes) or "",
        "object_role_graph": object_role_graph_hash(pdf_bytes),
    }
    for layer in ("F1", "F2"):
        font = fonts.get(layer, {})
        cmap = font.get("cmap") or {}
        widths = font.get("widths") or {}
        out[layer] = {
            "used_set": sorted(used.get(layer, set())),
            "tounicode": sorted(
                (int(cid), str(value))
                for cid, value in cmap.items()
            ),
            "w": sorted(
                (int(cid), int(width))
                for cid, width in widths.items()
            ),
        }
    return out


def assembly_signature(pdf_bytes: bytes) -> tuple[str, dict]:
    features = assembly_features(pdf_bytes)
    return _sha_json(features), features


def static_assets(pdf_bytes: bytes) -> dict:
    f3 = _extract_fontfile2(pdf_bytes, "F3") or b""
    indirect = _indirect_lengths(pdf_bytes)
    image_hashes: list[str] = []
    for match in _OBJ_BODY_RE.finditer(pdf_bytes):
        body = match.group(3)
        stream_match = re.search(rb"stream\r?\n", body)
        if not stream_match:
            continue
        header = body[:stream_match.start()]
        if not (
            b"/Subtype /Image" in header
            or b"/Subtype/Image" in header
        ):
            continue
        start = stream_match.end()
        length = _length_from_hdr(header, indirect)
        if length and length > 0:
            raw = body[start:start + length]
        else:
            end = body.find(b"endstream", start)
            if end < 0:
                continue
            raw = body[start:end].rstrip(b"\r\n")
        try:
            decoded = zlib.decompress(raw)
        except zlib.error:
            continue
        image_hashes.append(hashlib.sha256(decoded).hexdigest())
    image_hashes.sort()
    bundle_raw = "|".join(image_hashes).encode("ascii")
    return {
        "f3_sha256": hashlib.sha256(f3).hexdigest() if f3 else "",
        "image_count": len(image_hashes),
        "image_hashes": image_hashes,
        "image_bundle_sha256": (
            hashlib.sha256(bundle_raw).hexdigest() if image_hashes else ""
        ),
    }


def object_role_graph_hash(pdf_bytes: bytes) -> str:
    """Role edges without raw xref numbers (renumber-stable)."""
    edges: list[str] = []
    patterns = [
        (rb"/Type\s*/Page\b", "Page"),
        (rb"/Contents\s+\d+\s+0\s+R", "Page->Contents"),
        (rb"/Resources\s+\d+\s+0\s+R", "Page->Resources"),
        (rb"/Font\s*<<", "Resources->Font"),
        (rb"/DescendantFonts\s*\[\s*\d+\s+0\s+R", "Font->DescendantFont"),
        (rb"/FontDescriptor\s+\d+\s+0\s+R", "Font->FontDescriptor"),
        (rb"/FontFile2\s+\d+\s+0\s+R", "FontDescriptor->FontFile2"),
        (rb"/ToUnicode\s+\d+\s+0\s+R", "Font->ToUnicode"),
        (rb"/Subtype\s*/Image\b", "XObject->Image"),
        (rb"/Type\s*/XObject\b", "XObject"),
        (rb"/Producer\s*\(", "Info->Producer"),
        (rb"/Creator\s*\(", "Info->Creator"),
        (rb"/Subject\s*\(", "Info->Subject"),
        (rb"/ID\s*\[", "Trailer->ID"),
    ]
    for pat, role in patterns:
        n = len(re.findall(pat, pdf_bytes))
        if n:
            edges.append(f"{role}:{n}")
    return hashlib.sha256("|".join(edges).encode("ascii")).hexdigest()[:32]


def _content_ast_v2(pdf_bytes: bytes) -> str:
    """Operator skeleton with font-role transitions and Tj CID-length classes."""
    raw = content_stream_bytes(pdf_bytes) or b""
    if not raw:
        return ""
    tokens: list[str] = []
    # Strip literal strings but keep hex Tj length class.
    work = re.sub(rb"\((?:\\.|[^\\)])*\)", b"()", raw)

    for m in re.finditer(
        rb"(/(?:F\d+)\s+[\d.]+\s+Tf)|"
        rb"(BT|ET)|"
        rb"(<>?\s*Tj)|"
        rb"(<[0-9A-Fa-f]+>\s*Tj)|"
        rb"([\d.+-]+\s+[\d.+-]+\s+(?:Td|Tm|TD))|"
        rb"(Do)|"
        rb"(T\*|Tj|TJ|Tc|Tw|Tz|TL|Tr|Ts)",
        work,
    ):
        g = m.group(0)
        if g.startswith(b"/F"):
            fm = re.match(rb"/(F\d+)\s+([\d.]+)\s+Tf", g)
            if fm:
                tokens.append(f"Tf:{fm.group(1).decode()}:{fm.group(2).decode()}")
            continue
        if g in (b"BT", b"ET", b"Do", b"T*", b"Tj", b"TJ", b"Tc", b"Tw",
                 b"Tz", b"TL", b"Tr", b"Ts"):
            tokens.append(g.decode("ascii", "replace"))
            continue
        if b"Tj" in g and g.strip().startswith(b"<"):
            hx = re.match(rb"<([0-9A-Fa-f]*)>\s*Tj", g)
            n = len(hx.group(1)) // 2 if hx else 0
            tokens.append(f"TjCID:{n}")
            continue
        if b"Td" in g or b"Tm" in g or b"TD" in g:
            parts = g.split()
            if len(parts) >= 3:
                op = parts[-1].decode("ascii", "replace")
                nums = []
                for p in parts[:-1]:
                    try:
                        nums.append(f"{float(p):.3f}")
                    except ValueError:
                        nums.append("N")
                tokens.append(f"{op}:{'/'.join(nums)}")
            continue
        tokens.append("Tj")
    blob = "|".join(tokens).encode("ascii", "replace")
    return hashlib.sha256(blob).hexdigest()[:32]


def placement_residual_vector(pdf_bytes: bytes) -> dict:
    """Quantized residuals of value rows vs bank right column (~250pt)."""
    residuals: list[float] = []
    anomaly = False
    if not fitz:
        return {"residuals_q": [], "anomaly": False, "fingerprint": ""}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0] if doc.page_count else None
        if page is None:
            doc.close()
            return {"residuals_q": [], "anomaly": False, "fingerprint": ""}
        d = page.get_text("dict")
        doc.close()
    except Exception:
        return {"residuals_q": [], "anomaly": False, "fingerprint": ""}

    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            if not spans:
                continue
            txt = "".join(sp.get("text", "") for sp in spans).strip()
            if not txt or len(txt) < 2:
                continue
            # Skip left labels (x < 100).
            x0 = min(float(sp["bbox"][0]) for sp in spans if sp.get("bbox"))
            x1 = max(float(sp["bbox"][2]) for sp in spans if sp.get("bbox"))
            if x0 < 100:
                continue
            if x1 < 180:
                continue
            residual = x1 - _TARGET_RIGHT_PT
            q = round(residual / _RESIDUAL_QUANT) * _RESIDUAL_QUANT
            residuals.append(round(q, 2))
            if abs(residual) > 0.5:
                anomaly = True

    residuals_q = sorted(residuals)
    fp = hashlib.sha256(
        (",".join(f"{r:.2f}" for r in residuals_q) + f"|a={int(anomaly)}").encode()
    ).hexdigest()[:32]
    return {
        "residuals_q": residuals_q[:64],
        "anomaly": anomaly,
        "fingerprint": fp,
        "n": len(residuals_q),
        "any_off_lattice": anomaly,
    }


def generator_v2_fingerprint(pdf_bytes: bytes) -> tuple[str, dict]:
    payload = {
        "content_ast_v2": _content_ast_v2(pdf_bytes),
        "object_role_graph": object_role_graph_hash(pdf_bytes),
        "placement": placement_residual_vector(pdf_bytes).get("fingerprint", ""),
        "channel": _detect_channel(_pdf_text(pdf_bytes)),
    }
    return _sha_json(payload), payload


def complete_font_assembly_signature(pdf_bytes: bytes) -> tuple[str, dict]:
    """Full F1/F2 assembled pair — not individual glyphs."""
    used = _collect_used_by_font(pdf_bytes)
    fonts, _ = _font_objects(pdf_bytes)
    observations = extract_glyph_observations(pdf_bytes).get("glyphs") or {}
    layers: dict = {}
    for layer in ("F1", "F2"):
        font = fonts.get(layer, {})
        cmap = font.get("cmap") or {}
        widths = font.get("widths") or {}
        layer_obs = observations.get(layer) or {}
        by_gid: dict[int, str] = {}
        for _key, cur in layer_obs.items():
            gid = cur.get("gid")
            h = cur.get("raw_glyf_hash") or cur.get("outline_norm_hash") or ""
            if gid is None:
                continue
            by_gid[int(gid)] = str(h)
        fp = subset_builder_fingerprint(pdf_bytes, layer) or {}
        structural = {
            "table_order": fp.get("table_order") or fp.get("order") or [],
            "head": fp.get("head") or {},
            "hhea": fp.get("hhea") or {},
            "maxp": fp.get("maxp") or {},
        }
        # Prefer TTFont loca/hmtx snapshot when available.
        ttf = _extract_fontfile2(pdf_bytes, layer) or b""
        loca_n = 0
        hmtx_n = 0
        if ttf and TTFont:
            try:
                tt = TTFont(BytesIO(ttf))
                if "loca" in tt:
                    loca_n = len(getattr(tt["loca"], "locations", []) or [])
                if "hmtx" in tt:
                    hmtx_n = len(tt["hmtx"].metrics)
                tt.close()
            except Exception:
                pass
        layers[layer] = {
            "used_cids": sorted(int(c) for c in used.get(layer, set())),
            "glyf_by_gid": {str(g): h for g, h in sorted(by_gid.items())},
            "tounicode": sorted((int(c), str(v)) for c, v in cmap.items()),
            "w": sorted((int(c), int(w)) for c, w in widths.items()),
            "loca_n": loca_n,
            "hmtx_n": hmtx_n,
            "structural": structural,
        }
    sig = _sha_json(layers)
    return sig, layers


def _atlas_gid_hash_index(data: dict | None = None) -> dict[tuple[str, int], set[str]]:
    """Prefer reassembled JSON glyph hashes; fall back to glyph atlas."""
    idx: dict[tuple[str, int], set[str]] = {}
    payload = data or {}
    stored = payload.get("trusted_glyph_hashes_by_role_gid") or {}
    for key, hashes in stored.items():
        try:
            font, gid_s = str(key).split(":", 1)
            gid = int(gid_s)
        except ValueError:
            continue
        bucket = idx.setdefault((font, gid), set())
        for h in hashes or []:
            if h:
                bucket.add(str(h))

    atlas = load_atlas().get("glyphs") or {}
    for key, ref in atlas.items():
        font = str(ref.get("font_role") or "")
        gid = ref.get("gid")
        if not font and ":" in key:
            font = key.split(":", 1)[0]
        if gid is None:
            continue
        hashes = ref.get("raw_glyf_hash") or []
        if not isinstance(hashes, list):
            hashes = [hashes] if hashes else []
        outline = ref.get("outline_norm_hash") or []
        if not isinstance(outline, list):
            outline = [outline] if outline else []
        bucket = idx.setdefault((font, int(gid)), set())
        for h in list(hashes) + list(outline):
            if h:
                bucket.add(str(h))
    return idx


def evidence_canonical_glyph_mosaic(
    pdf_bytes: bytes,
    data: dict | None = None,
) -> tuple[bool, dict]:
    """Every used F1/F2 glyph is a bank component (font role + GID in corpus).

    When raw_glyf_hash is available it must match the trusted hash set for that
    (font, GID). Composites often lack stable compile hashes — for those, presence
    of the GID in the trusted original corpus is sufficient mosaic evidence.
    """
    idx = _atlas_gid_hash_index(data)
    # Also accept GID keys that appear in corpus even with empty hash lists.
    stored = (data or {}).get("trusted_glyph_hashes_by_role_gid") or {}
    known_gids: set[tuple[str, int]] = set(idx.keys())
    for key in stored:
        try:
            font, gid_s = str(key).split(":", 1)
            known_gids.add((font, int(gid_s)))
        except ValueError:
            pass
    # Atlas keys F1:unicode:cid still encode gid in entry.
    atlas = load_atlas().get("glyphs") or {}
    for _key, ref in atlas.items():
        font = str(ref.get("font_role") or "")
        gid = ref.get("gid")
        if font and gid is not None:
            known_gids.add((font, int(gid)))

    observations = extract_glyph_observations(pdf_bytes).get("glyphs") or {}
    checked = 0
    missing: list[str] = []
    mismatched: list[str] = []
    per_font: dict[str, int] = {}

    for layer in ("F1", "F2"):
        layer_glyphs = observations.get(layer) or {}
        per_font[layer] = len(layer_glyphs)
        for glyph_key, current in layer_glyphs.items():
            checked += 1
            gid = current.get("gid")
            if gid is None:
                missing.append(f"{layer}:{glyph_key}:no_gid")
                continue
            gid_i = int(gid)
            if (layer, gid_i) not in known_gids:
                missing.append(f"{layer}:{glyph_key}:gid={gid_i}")
                continue
            h = current.get("raw_glyf_hash") or ""
            oh = current.get("outline_norm_hash") or ""
            allowed = idx.get((layer, gid_i), set())
            probe = {x for x in (h, oh) if x}
            # Hash match required only when both sides have hashes.
            if probe and allowed and not (probe & allowed):
                mismatched.append(f"{layer}:{glyph_key}:gid={gid_i}")

    complete = (
        per_font.get("F1", 0) > 0
        and per_font.get("F2", 0) > 0
        and checked > 0
        and not missing
        and not mismatched
    )
    return complete, {
        "checked": checked,
        "per_font": per_font,
        "missing": missing[:12],
        "mismatched": mismatched[:12],
        "ok": complete,
        "known_gids": len(known_gids),
    }


def evidence_static_asset_bundle_exact(
    pdf_bytes: bytes,
    *,
    producer: str,
    creator: str,
    data: dict,
) -> tuple[bool, dict]:
    profile_ok = claims_confirmed_tbank_profile(
        pdf_bytes, producer=producer, creator=creator,
    )
    meta = _pdf_meta(pdf_bytes)
    subject = meta.get("subject") or meta.get("Subject") or ""
    subject_ok = _SUBJECT_MARKER.lower() in subject.lower()
    assets = static_assets(pdf_bytes)
    trusted_f3 = set(data.get("trusted_f3_sha256") or ())
    trusted_images = set(data.get("trusted_image_bundle_sha256") or ())
    static_ok = (
        assets["image_count"] == 4
        and assets["f3_sha256"] in trusted_f3
        and assets["image_bundle_sha256"] in trusted_images
    )
    ok = bool(profile_ok and subject_ok and static_ok)
    return ok, {
        "jasper_openpdf_profile": profile_ok,
        "subject_ok": subject_ok,
        "subject": subject[:80],
        "static_assets": {
            "image_count": assets["image_count"],
            "f3_trusted": assets["f3_sha256"] in trusted_f3,
            "image_bundle_trusted": assets["image_bundle_sha256"] in trusted_images,
            "f3_sha256": assets["f3_sha256"],
            "image_bundle_sha256": assets["image_bundle_sha256"],
        },
        "ok": ok,
    }


def evidence_untrusted_complete_font_assembly(
    pdf_bytes: bytes,
    data: dict,
) -> tuple[bool, dict]:
    trusted = set(data.get("trusted_complete_font_assemblies") or ())
    sig, layers = complete_font_assembly_signature(pdf_bytes)
    if not trusted:
        return False, {
            "signature": sig,
            "trusted_n": 0,
            "ok": False,
            "reason": "trusted_complete_font_assemblies_empty",
        }
    unknown = sig not in trusted
    return unknown, {
        "signature": sig,
        "trusted_n": len(trusted),
        "seen_in_originals": not unknown,
        "ok": unknown,
        "f1_used": len((layers.get("F1") or {}).get("used_cids") or []),
        "f2_used": len((layers.get("F2") or {}).get("used_cids") or []),
    }


def evidence_rebuilt_cmap_w_ast_assembly(
    pdf_bytes: bytes,
    data: dict,
) -> tuple[bool, dict]:
    trusted = set(data.get("trusted_assembly_signatures") or ())
    sig, features = assembly_signature(pdf_bytes)
    if not trusted:
        return False, {"signature": sig, "ok": False, "reason": "trusted_empty"}
    unknown = sig not in trusted
    return unknown, {
        "signature": sig,
        "content_ast": features.get("content_ast", ""),
        "channel": features.get("channel", ""),
        "object_role_graph": features.get("object_role_graph", ""),
        "seen_in_originals": not unknown,
        "ok": unknown,
    }


def evidence_generator_v2_provenance(
    pdf_bytes: bytes,
    data: dict,
) -> tuple[bool, dict]:
    prov = data.get("generator_provenance") or {}
    fp, payload = generator_v2_fingerprint(pdf_bytes)
    v2_fps = set(prov.get("generator_v2_fingerprints") or ())
    v2_asts = set(prov.get("content_ast_v2") or ())
    placement = placement_residual_vector(pdf_bytes)
    match_fp = fp in v2_fps
    match_ast = payload.get("content_ast_v2", "") in v2_asts
    # Require off-lattice residual (generator-v2 quantization) OR exact fp match.
    ok = bool((match_fp or match_ast) and (
        placement.get("any_off_lattice") or match_fp
    ))
    # If fingerprints list is populated and exact fp hits, accept even without anomaly
    # (anomaly may be zero after future generator tweak that still matches fp).
    if match_fp:
        ok = True
    return ok, {
        "fingerprint": fp,
        "content_ast_v2": payload.get("content_ast_v2", ""),
        "match_fingerprint": match_fp,
        "match_ast_v2": match_ast,
        "placement_anomaly": placement.get("any_off_lattice"),
        "placement_n": placement.get("n"),
        "ok": ok,
    }


def evidence_generator_v1_provenance(
    pdf_bytes: bytes,
    data: dict,
    features: dict,
) -> tuple[bool, dict]:
    prov = data.get("generator_provenance") or {}
    known_skeletons = set(prov.get("content_ast_v1") or ())
    skeleton_match = features.get("content_ast", "") in known_skeletons
    reported_series = False
    try:
        reported_series = check_known_fake(pdf_bytes).get("score", 0) > 0
    except Exception:
        reported_series = False
    ok = bool(skeleton_match or reported_series)
    return ok, {
        "content_ast_match": skeleton_match,
        "confirmed_series_file": reported_series,
        "ok": ok,
    }


def check_reassembled_bank_assets(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> ReassembledResult:
    out = ReassembledResult()
    data = _load_data()
    if not data:
        out.stats["skipped"] = "trusted_reassembly_index_missing"
        return out

    # 1) Static asset bundle (Jasper/OpenPDF + F3 + 4 images + Subject)
    e1, s1 = evidence_static_asset_bundle_exact(
        pdf_bytes, producer=producer, creator=creator, data=data,
    )
    out.stats["E1_STATIC_ASSET_BUNDLE"] = s1
    if not e1:
        return out

    # 2) Canonical glyph mosaic (stolen bank glyphs)
    e2, s2 = evidence_canonical_glyph_mosaic(pdf_bytes, data)
    out.stats["E2_CANONICAL_GLYPH_MOSAIC"] = s2
    mismatched = list(s2.get("mismatched") or [])
    missing = list(s2.get("missing") or [])
    # E1 shell + known GIDs with wrong outline hashes = edited/transplanted glyphs.
    # Silent early-return here previously let SEQ CLEANs through (0 mismatches on
    # genuines n=128; SEQ often 2–10).
    if mismatched:
        out.flags.append(ReassembledFlag(
            "TBANK_GLYPH_MOSAIC_HASH_MISMATCH",
            (
                f"доверенный Jasper/OpenPDF asset-bundle, но {len(mismatched)} "
                f"used-glyph outline hash ≠ trusted mosaic "
                f"(пример {mismatched[0]}) — пересборка/правка глифов"
            ),
            rule_id="K-TBANK-GLYPH-MOSAIC-HASH-MISMATCH-001",
            tier="A",
        ))
        return out
    # Missing GID / letter outside the trusted mosaic is novelty, not forgery:
    # genuines may use rare Cyrillic (Ж/Й/Ъ/Ы/Ь…) that the atlas simply never
    # indexed. Do not HARD on absence — only HASH_MISMATCH above (known GID,
    # wrong outline) is evidence. Keep stats; continue the reassembly stack.
    if missing:
        out.stats["mosaic_incomplete_diag"] = missing[:12]
    if not e2:
        return out

    # 3) Untrusted complete F1/F2 assembly
    e3, s3 = evidence_untrusted_complete_font_assembly(pdf_bytes, data)
    out.stats["E3_UNTRUSTED_COMPLETE_FONT_ASSEMBLY"] = s3

    # 4) Rebuilt CMap/W/AST assembly unknown to originals
    e4, s4 = evidence_rebuilt_cmap_w_ast_assembly(pdf_bytes, data)
    out.stats["E4_REBUILT_CMAP_W_AST_ASSEMBLY"] = s4

    # 5) Generator provenance v2 (and v1 fallback)
    e5, s5 = evidence_generator_v2_provenance(pdf_bytes, data)
    out.stats["E5_GENERATOR_V2_PROVENANCE"] = s5
    e5_v1, s5_v1 = evidence_generator_v1_provenance(
        pdf_bytes, data, {"content_ast": s4.get("content_ast", "")},
    )
    out.stats["E5_GENERATOR_V1_PROVENANCE"] = s5_v1

    out.stats["evidence"] = {
        "E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5_v2": e5, "E5_v1": e5_v1,
    }

    if e1 and e2 and e3 and e4 and e5:
        out.flags.append(ReassembledFlag(
            CODE_V2,
            (
                "TBANK_STATIC_ASSET_BUNDLE_EXACT + TBANK_CANONICAL_GLYPH_MOSAIC + "
                "TBANK_UNTRUSTED_COMPLETE_FONT_ASSEMBLY + "
                "TBANK_REBUILT_CMAP_W_AST_ASSEMBLY + TBANK_GENERATOR_V2_PROVENANCE: "
                "доверенные банковские assets/glyph собраны в неизвестную complete "
                f"assembly с generator fingerprint v2 "
                f"(fp={s5.get('fingerprint', '')[:16]}, "
                f"ast_v2={s5.get('content_ast_v2', '')[:16]}, "
                f"font_asm={s3.get('signature', '')[:16]}, "
                f"cmap_ast={s4.get('signature', '')[:16]})"
            ),
        ))
        return out

    # Backward-compatible v1 KNOWN path.
    if e1 and e2 and e4 and e5_v1:
        out.flags.append(ReassembledFlag(
            CODE,
            (
                "точный JasperReports/OpenPDF профиль использует только доверенные "
                "F1/F2 glyph-программы и статические F3/image assets, но сочетание "
                "content AST + F1/F2 used-set + ToUnicode + /W отсутствует во всех "
                f"{data.get('corpus_samples', 0)} доверенных документах; "
                f"подтверждена provenance генератора v1 "
                f"(content_ast_match={s5_v1.get('content_ast_match')}, "
                f"confirmed_series={s5_v1.get('confirmed_series_file')})"
            ),
        ))
    return out
