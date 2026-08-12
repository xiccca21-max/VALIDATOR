#!/usr/bin/env python3
"""Materialize runtime atlas JSON names expected by alfa_v2 loaders."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "detector" / "alfa_v2" / "atlas_data"


def _load(name: str) -> dict:
    return json.loads((ATLAS / name).read_text(encoding="utf-8"))


def _dump(name: str, payload: dict) -> None:
    path = ATLAS / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path.name} ({path.stat().st_size} bytes)")


def _emitter(name: str) -> str:
    return "oracle" if name == "oracle_bi" else "quartz"


def main() -> None:
    manifest = _load("manifest.v1.json")
    streams = _load("streams-images.v1.json")
    glyphs = _load("glyph-geometry.v1.json")
    fonts = _load("font-inventory.v1.json")
    sbp = _load("sbp-segmentation.v1.json")

    sha_to_emitter = {
        row["sha256"]: _emitter(row["emitter"]) for row in manifest["files"]
    }

    # --- flate_profiles.json -------------------------------------------------
    # Versioned streams atlas keeps provenance hashes, not zlib levels.
    # Runtime serializer still needs role-aware level candidates.
    _dump(
        "flate_profiles.json",
        {
            "oracle": {
                "content": {"levels": [6]},
                "font": {"levels": [6]},
                "tounicode": {"levels": [6]},
                "image": {"levels": [6]},
                "xref": {"levels": [6]},
            },
            "quartz": {
                "content": {"levels": [6, 9]},
                "font": {"levels": [6, 9]},
                "tounicode": {"levels": [6, 9]},
                "image": {"levels": [6, 9]},
                "icc": {"levels": [6, 9]},
                "xref": {"levels": [6, 9]},
            },
        },
    )

    # --- static_assets.json --------------------------------------------------
    images: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    icc: dict[str, set[str]] = defaultdict(set)
    for row in streams["static_images_by_file"]:
        emitter = sha_to_emitter[row["file_sha256"]]
        for image in row["images"]:
            role = f"{image['width']}x{image['height']}"
            images[emitter][role].add(image["decoded_sha256"])
            if image.get("icc_sha256"):
                icc[emitter].add(image["icc_sha256"])

    static_assets = {}
    for emitter, roles in images.items():
        stable = {
            role: sorted(values)
            for role, values in roles.items()
            if len(values) == 1
        }
        payload = {"images": stable}
        if icc.get(emitter):
            payload["icc"] = sorted(icc[emitter])
        static_assets[emitter] = payload
    _dump("static_assets.json", static_assets)

    # --- glyph_atlas.json ----------------------------------------------------
    glyph_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for obs in glyphs["observations"]:
        emitter = sha_to_emitter[obs["file_sha256"]]
        char = obs.get("unicode") or ""
        digest = obs.get("geometry_sha256")
        if not char or not digest:
            continue
        glyph_map[emitter][char].add(digest)
        glyph_map[emitter][f"{ord(char):04X}"].add(digest)

    fontfile2: dict[str, set[str]] = defaultdict(set)
    for row in fonts["files"]:
        emitter = sha_to_emitter[row["file_sha256"]]
        for font in row["fonts"]:
            digest = font.get("fontfile2_sha256")
            if digest:
                fontfile2[emitter].add(digest)

    glyph_atlas = {}
    for emitter in sorted(set(glyph_map) | set(fontfile2)):
        glyph_atlas[emitter] = {
            "glyphs": {
                key: {"outline_hashes": sorted(values)}
                for key, values in sorted(glyph_map.get(emitter, {}).items())
            },
            "fontfile2_sha256": sorted(fontfile2.get(emitter, ())),
        }
    _dump("glyph_atlas.json", glyph_atlas)

    # --- content_ast.json ----------------------------------------------------
    # Operator skeletons are not captured in the versioned atlas yet; keep an
    # empty contract so loaders succeed and skeleton checks stay no-ops.
    _dump(
        "content_ast.json",
        {
            "oracle": {"operator_skeleton_sha256": []},
            "quartz": {"operator_skeleton_sha256": []},
        },
    )

    # --- sbp runtime helper (entries already compatible) ---------------------
    _dump(
        "alfa_sbp_atlas.json",
        {
            "schema": "alfa-v2-sbp-runtime",
            "version": sbp.get("version", "1.0.0"),
            "entries": sbp.get("entries", []),
            "segmentation": sbp.get("segmentation", []),
        },
    )


if __name__ == "__main__":
    main()
