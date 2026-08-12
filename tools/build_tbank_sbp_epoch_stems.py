"""Build corpus-backed SBP profile epochs and receipt-stem index."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.sbp_cipher import extract_receipt_datetime, extract_sbp_opid


CORPUS = Path.home() / "OneDrive" / "Desktop" / "чеки" / "т банк"
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "detector"
    / "atlas_data"
    / "tbank_sbp_epoch_stems.json"
)
RECEIPT_RE = re.compile(r"1-\d{3}-\d{3}-\d{3}-\d{3}")


def main() -> None:
    epochs: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    stems: dict[str, list[dict[str, str]]] = defaultdict(list)
    all_dates: list[str] = []
    scanned = 0

    for path in sorted(CORPUS.glob("*.pdf")):
        try:
            doc = fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception:
            continue
        scanned += 1
        opid = extract_sbp_opid(text) or ""
        dt = extract_receipt_datetime(text, prefer_first_line=True)
        date = dt.date().isoformat() if dt else ""
        receipt_match = RECEIPT_RE.search(text)
        receipt = receipt_match.group(0) if receipt_match else ""

        if date:
            all_dates.append(date)
        if len(opid) == 32 and date:
            key = (opid[17:19], opid[22:27], opid[26:32])
            epochs[key].append(date)
        if receipt:
            stem = receipt.rsplit("-", 1)[0]
            item = {"receipt": receipt, "opid": opid, "date": date}
            if item not in stems[stem]:
                stems[stem].append(item)

    corpus_max = max(all_dates) if all_dates else ""
    epoch_json: dict[str, dict] = {}
    for key, dates in sorted(epochs.items()):
        unique = sorted(set(dates))
        epoch_json["|".join(key)] = {
            "first_date": unique[0],
            "last_date": unique[-1],
            "samples": len(dates),
            "dates": unique,
        }

    payload = {
        "version": "1.0.0",
        "rule_ids": [
            "T-TBANK-SBP-PROFILE-EPOCH-001",
            "T-TBANK-RECEIPT-STEM-REUSE-001",
        ],
        "corpus_dir": str(CORPUS),
        "corpus_samples": scanned,
        "corpus_last_date": corpus_max,
        "profiles": epoch_json,
        "receipt_stems": dict(sorted(stems.items())),
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"wrote {OUTPUT}: profiles={len(epoch_json)}, "
        f"stems={len(stems)}, samples={scanned}"
    )


if __name__ == "__main__":
    main()
