"""Quick regression for T-Bank v6.0 engine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector.tbank import VALIDATOR_VERSION, analyze


def main() -> None:
    print("version", VALIDATOR_VERSION)

    anchors = [
        (Path(r"C:\Users\fanis\Downloads\Receipt (6).pdf"), "REG-O-002", "ЧИСТО"),
        (Path(r"C:\Users\fanis\Downloads\receipt_12.07.2026 (4).pdf"), "REG-O-004", "ЧИСТО"),
        (Path(r"C:\Users\fanis\Downloads\receipt_10.07.2026 (28).pdf"), "REG-F-002", "ФЕЙК"),
    ]
    for path, reg, expect in anchors:
        if not path.exists():
            print(reg, "MISSING", path)
            continue
        r = analyze(path.read_bytes())
        ok = r["verdict"] == expect
        print(reg, path.name, "->", r["verdict"], "OK" if ok else "FAIL", r["flags"][:3])

    orig = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
    if orig.exists():
        fps = 0
        total = 0
        for p in sorted(orig.glob("*.pdf")):
            total += 1
            r = analyze(p.read_bytes())
            if r["verdict"] == "ФЕЙК":
                fps += 1
                print("FP", p.name, r["flags"][:2])
        print(f"REG-O-001: {total - fps}/{total} originals ЧИСТО, FP={fps}")
    else:
        print("REG-O-001 corpus missing")

    fake_root = Path(
        r"C:\Users\fanis\OneDrive\Desktop\samaya-ohuenaya-versiya\output\tbank_all25"
    )
    if fake_root.exists():
        caught = missed = 0
        missed_names: list[str] = []
        for folder in ("sbp", "card_sber", "card_tbank", "nocomm", "phone"):
            d = fake_root / folder
            if not d.exists():
                continue
            for p in d.glob("*.pdf"):
                r = analyze(p.read_bytes())
                if r["verdict"] == "ФЕЙК":
                    caught += 1
                else:
                    missed += 1
                    missed_names.append(f"{folder}/{p.name}")
        print(f"Matrix fakes: caught {caught}/{caught + missed}, missed={missed}")
        for n in missed_names[:10]:
            print("  miss", n)


if __name__ == "__main__":
    main()
