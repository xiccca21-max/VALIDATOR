"""Build trusted combinations for K-TBANK-REASSEMBLED-SUBSET-001 (v1 + v2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.tbank_reassembled_subset import (
    assembly_signature,
    complete_font_assembly_signature,
    generator_v2_fingerprint,
    static_assets,
)
from detector.tbank_glyph_atlas import extract_glyph_observations
from detector.tbank_v6.rules import KNOWN_GENERATOR_SKELETONS
from detector.tbank_jasper_profile import claims_confirmed_tbank_profile
import fitz


CORPUS_CANDIDATES = [
    Path.home() / "OneDrive" / "Desktop" / "чеки" / "Новая папка",
    Path.home() / "OneDrive" / "Desktop" / "чеки" / "т банк",
]
FAKE_DIR = Path.home() / "OneDrive" / "Desktop" / "фейки хорошие"
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "detector"
    / "atlas_data"
    / "tbank_reassembled_subset.json"
)


def _pick_corpus() -> Path:
    for path in CORPUS_CANDIDATES:
        if path.is_dir() and any(path.glob("*.pdf")):
            return path
    raise SystemExit("no original corpus found")


def _is_tbank_receipt(pdf_bytes: bytes) -> bool:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = doc.metadata or {}
        producer = meta.get("producer") or ""
        creator = meta.get("creator") or ""
        subject = meta.get("subject") or ""
        doc.close()
    except Exception:
        return False
    if not claims_confirmed_tbank_profile(pdf_bytes, producer=producer, creator=creator):
        return False
    return "/reports/IB/Receipt" in subject


def _collect_glyph_hashes(pdf_bytes: bytes, sink: dict[str, set[str]]) -> None:
    obs = extract_glyph_observations(pdf_bytes).get("glyphs") or {}
    for layer in ("F1", "F2"):
        for _key, cur in (obs.get(layer) or {}).items():
            gid = cur.get("gid")
            if gid is None:
                continue
            key = f"{layer}:{int(gid)}"
            sink.setdefault(key, set())
            h = cur.get("raw_glyf_hash") or cur.get("outline_norm_hash") or ""
            if h:
                sink[key].add(h)


def main() -> None:
    corpus = _pick_corpus()
    assemblies: set[str] = set()
    font_assemblies: set[str] = set()
    f3_hashes: set[str] = set()
    image_bundles: set[str] = set()
    glyph_hashes: dict[str, set[str]] = {}
    scanned = 0

    for path in sorted(corpus.glob("*.pdf")):
        try:
            pdf_bytes = path.read_bytes()
            signature, _ = assembly_signature(pdf_bytes)
            font_sig, _ = complete_font_assembly_signature(pdf_bytes)
            assets = static_assets(pdf_bytes)
            _collect_glyph_hashes(pdf_bytes, glyph_hashes)
        except Exception as exc:
            print("skip original", path.name, exc)
            continue
        scanned += 1
        if signature:
            assemblies.add(signature)
        if font_sig:
            font_assemblies.add(font_sig)
        if assets["f3_sha256"]:
            f3_hashes.add(assets["f3_sha256"])
        if assets["image_count"] == 4 and assets["image_bundle_sha256"]:
            image_bundles.add(assets["image_bundle_sha256"])

    v2_fps: set[str] = set()
    v2_asts: set[str] = set()
    fake_n = 0
    if FAKE_DIR.is_dir():
        for path in sorted(FAKE_DIR.glob("*.pdf")):
            try:
                pdf_bytes = path.read_bytes()
                if not _is_tbank_receipt(pdf_bytes):
                    continue
                fp, payload = generator_v2_fingerprint(pdf_bytes)
            except Exception as exc:
                print("skip fake", path.name, exc)
                continue
            fake_n += 1
            if fp:
                v2_fps.add(fp)
            ast = payload.get("content_ast_v2") or ""
            if ast:
                v2_asts.add(ast)
            print("fake fingerprint", path.name, fp[:16], "ast", ast[:16])

    payload = {
        "version": "2.0.0",
        "rule_id": "K-TBANK-REASSEMBLED-SUBSET-001",
        "code": "TBANK_REASSEMBLED_BANK_ASSETS",
        "code_v2": "TBANK_REASSEMBLED_BANK_ASSETS_V2",
        "corpus_dir": str(corpus),
        "corpus_samples": scanned,
        "trusted_assembly_signatures": sorted(assemblies),
        "trusted_complete_font_assemblies": sorted(font_assemblies),
        "trusted_f3_sha256": sorted(f3_hashes),
        "trusted_image_bundle_sha256": sorted(image_bundles),
        "trusted_glyph_hashes_by_role_gid": {
            k: sorted(v) for k, v in sorted(glyph_hashes.items())
        },
        "generator_provenance": {
            "versions": [
                "tbank_generator_content_ast_v1",
                "tbank_generator_content_ast_v2",
            ],
            "content_ast_v1": sorted(KNOWN_GENERATOR_SKELETONS),
            "content_ast_v2": sorted(v2_asts),
            "generator_v2_fingerprints": sorted(v2_fps),
            "fake_samples_used": fake_n,
        },
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"wrote {OUTPUT}: originals={scanned}, assemblies={len(assemblies)}, "
        f"font_assemblies={len(font_assemblies)}, f3={len(f3_hashes)}, "
        f"image_bundles={len(image_bundles)}, glyph_gid_keys={len(glyph_hashes)}, "
        f"fakes={fake_n}, v2_fp={len(v2_fps)}, v2_ast={len(v2_asts)}"
    )


if __name__ == "__main__":
    main()
