"""Rebuild channel_skeleton_hashes in tbank_invariants.json."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.structure import content_skeleton_hash
from detector.corpus_profiles import detect_receipt_channel

ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
INV = ROOT / "detector" / "tbank_invariants.json"


def main() -> None:
    by_ch: dict[str, set[str]] = defaultdict(set)
    for f in sorted(ORIG.glob("*.pdf")):
        b = f.read_bytes()
        text = fitz.open(stream=b, filetype="pdf")[0].get_text()
        ch = detect_receipt_channel(text)
        sk = content_skeleton_hash(b)
        if ch and sk:
            by_ch[ch].add(sk)

    inv = json.loads(INV.read_text(encoding="utf-8"))
    inv["channel_skeleton_hashes"] = {ch: sorted(hashes) for ch, hashes in sorted(by_ch.items())}
    INV.write_text(json.dumps(inv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({ch: len(hs) for ch, hs in inv["channel_skeleton_hashes"].items()})


if __name__ == "__main__":
    main()
