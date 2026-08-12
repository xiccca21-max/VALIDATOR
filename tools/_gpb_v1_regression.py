"""GPB v1 regression: 5 GPB originals → ЧИСТО; 2 Sber SHA → Sber validator."""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.gazprombank import analyze as analyze_shim
from detector.gpb_profiles import is_excluded_sber_hash
from detector.gpb_v1.engine import analyze as analyze_v1

CORPUS = r"C:\Users\fanis\OneDrive\Desktop\газпромбанк оригинал"
SBER_PREFIXES = ("bdaec803", "31976c7f")


def main() -> int:
    pdfs = sorted(
        os.path.join(CORPUS, f)
        for f in os.listdir(CORPUS)
        if f.lower().endswith(".pdf")
    )
    print(f"Corpus: {len(pdfs)} PDF")

    gpb_files: list[str] = []
    sber_files: list[str] = []
    for path in pdfs:
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if is_excluded_sber_hash(h):
            sber_files.append(os.path.basename(path))
        else:
            gpb_files.append(os.path.basename(path))

    print(f"GPB expected: {len(gpb_files)} | Sber reroute: {len(sber_files)}")

    v1_ok = 0
    v1_failures: list[str] = []
    for path in pdfs:
        name = os.path.basename(path)
        if name in sber_files:
            continue
        data = open(path, "rb").read()
        v1 = analyze_v1(data)
        if v1.get("verdict") == "ЧИСТО":
            v1_ok += 1
        else:
            v1_failures.append(
                f"{name} | family={v1.get('details', {}).get('family')} "
                f"flags={v1.get('flags')}"
            )

    reroute_ok = 0
    reroute_failures: list[str] = []
    for path in pdfs:
        name = os.path.basename(path)
        data = open(path, "rb").read()
        shim = analyze_shim(data)
        details = shim.get("details") or {}
        if name in sber_files:
            rr = details.get("gpb_reroute") or {}
            if rr.get("target") == "sber" and shim.get("verdict") == "ЧИСТО":
                reroute_ok += 1
            else:
                reroute_failures.append(
                    f"{name} | verdict={shim.get('verdict')} reroute={rr}"
                )
        elif shim.get("verdict") != "ЧИСТО":
            reroute_failures.append(f"{name} | shim verdict={shim.get('verdict')}")

    print(f"GPB v1:        {v1_ok}/{len(gpb_files)} ЧИСТО")
    print(f"Sber reroute:  {reroute_ok}/{len(sber_files)} OK")
    if v1_failures:
        print("GPB v1 failures:")
        for f in v1_failures:
            print(f"  {f}")
    if reroute_failures:
        print("Reroute failures:")
        for f in reroute_failures:
            print(f"  {f}")

    if v1_failures or reroute_failures:
        return 1
    print("REG-O-001 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
