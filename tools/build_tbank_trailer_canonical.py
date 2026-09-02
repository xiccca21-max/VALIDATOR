"""Build confirmed T-Bank trailer /ID -> decoded /Contents SHA-256 registry."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.structure import content_stream_bytes  # noqa: E402
from detector.tbank_id_reuse import extract_trailer_id_pair  # noqa: E402

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
OUTPUT = ROOT / "detector" / "tbank_trailer_canonical.json"


def main() -> None:
    registry: dict[str, str] = {}
    permanent_ids: dict[str, str] = {}
    for path in sorted(CORPUS.glob("*.pdf")):
        pdf = path.read_bytes()
        id0, id1 = extract_trailer_id_pair(pdf)
        if not id0 or not id1:
            continue
        content_sha = hashlib.sha256(content_stream_bytes(pdf) or b"").hexdigest()
        key = f"{id0}:{id1}"
        previous = registry.get(key)
        if previous and previous != content_sha:
            raise RuntimeError(f"canonical /ID collision with different content: {path}")
        previous_id0 = permanent_ids.get(id0)
        if previous_id0 and previous_id0 != content_sha:
            raise RuntimeError(
                f"canonical permanent /ID[0] collision with different content: {path}"
            )
        registry[key] = content_sha
        permanent_ids[id0] = content_sha
    OUTPUT.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(registry)} canonical identities to {OUTPUT}")


if __name__ == "__main__":
    main()
