"""K-TBANK-SBP-ROUTE-MARKER-001 regression — fakes must be ФЕЙК, route-profile originals ЧИСТО."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from detector.reputation import file_hash
from detector.sbp_cipher import extract_sbp_opid
from detector.tbank import analyze

FAKES = [
    os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "супер фейк.pdf"),
    os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "фейк.pdf"),
    os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "фейк(1).pdf"),
]
CORPUS = r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк"
_CONFIRMED_PROFILES = {
    ("G1", "00117"),
    ("00", "00116"),
    ("B1", "00117"),
    ("B0", "00116"),
}


def _route_profile(path: str) -> tuple[str, str] | None:
    doc = fitz.open(path)
    text = doc[0].get_text() if doc.page_count else ""
    doc.close()
    opid = extract_sbp_opid(text)
    if not opid or len(opid) != 32:
        return None
    return opid[17:19], opid[22:27]


def main() -> int:
    failures: list[str] = []

    fake_paths = [p for p in FAKES if os.path.isfile(p)]
    if not fake_paths:
        failures.append("no fake PDFs found in Downloads")
    for path in fake_paths:
        data = open(path, "rb").read()
        r = analyze(data, file_hash(data))
        if r.get("verdict") != "ФЕЙК":
            failures.append(
                f"FAKE {os.path.basename(path)}: expected ФЕЙК got {r.get('verdict')} "
                f"flags={r.get('flags', [])[:4]}"
            )

    if not os.path.isdir(CORPUS):
        failures.append(f"MISSING corpus {CORPUS}")
    else:
        matched = 0
        for name in sorted(os.listdir(CORPUS)):
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(CORPUS, name)
            prof = _route_profile(path)
            if prof not in _CONFIRMED_PROFILES:
                continue
            matched += 1
            data = open(path, "rb").read()
            r = analyze(data, file_hash(data))
            if r.get("verdict") != "ЧИСТО":
                sbp_flags = [
                    f for f in r.get("flags", [])
                    if "SBP" in f or "GRAMMAR" in f or "ROUTE" in f
                ]
                failures.append(
                    f"ORIGINAL corpus/{name} profile={prof}: {r.get('verdict')} "
                    f"sbp={sbp_flags[:3]}"
                )
        if matched < 33:
            failures.append(f"expected ≥33 route-profile originals, found {matched}")

    if failures:
        print("FAIL", len(failures))
        for f in failures:
            print(" ", f)
        return 1
    print(f"PASS route-marker regression ({len(fake_paths)} fakes, 33+ originals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
