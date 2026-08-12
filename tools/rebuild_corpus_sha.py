#!/usr/bin/env python3
"""Rebuild content_decoded_sha.global in corpus_spec from genuine T-Bank PDFs only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.corpus_profiles import CORPUS_ORIGINALS
from detector.structure import content_stream_bytes

SPEC = ROOT / "detector" / "data" / "tbank_template" / "corpus_spec.json"
EXTRA_DIRS = [
    Path.home() / "OneDrive" / "Desktop" / "чеки" / "т банк",
    Path.home() / "Downloads",
]


def collect_paths() -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for name in CORPUS_ORIGINALS:
        p = Path.home() / "Downloads" / name
        if p.is_file() and str(p) not in seen:
            seen.add(str(p))
            paths.append(p)
    for folder in EXTRA_DIRS:
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.pdf")):
            if str(p) not in seen:
                seen.add(str(p))
                paths.append(p)
    return paths


def main() -> None:
    hashes: set[str] = set()
    for p in collect_paths():
        cs = content_stream_bytes(p.read_bytes())
        if not cs:
            continue
        hashes.add(hashlib.sha256(cs).hexdigest()[:16])

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["content_decoded_sha"]["global"] = sorted(hashes)
    SPEC.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(hashes)} content stream SHAs to {SPEC}")


if __name__ == "__main__":
    main()
