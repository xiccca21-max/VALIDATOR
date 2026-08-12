"""Sparse9 v1 regression: 21 PDF / 15 unique SHA → ЧИСТО (REG-O-001)."""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.sparse9_v1.engine import analyze as analyze_v1

CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "_sparse9_corpus_full",
)

SHA_BANK = {
    "70b7d9831010e8dc306c37bf28d4911456bf1d38c284ee99dc6bf50dd364895f": "wbbank",
    "dd4d0214bcb3f278c13093daec5a73a929e4afaacf8a105b532031fa12925c60": "otp",
    "10ba835806c812c4aeeed5e841aa851e33ca6332211d14cf917250aaa8a720e8": "otp",
    "bff01559f12a03e5f5ffa19453708618078601768ae2e1a7c9e3b9449da1a6b9": "psb",
    "cf8553af700a03da26f5c2fc33c05119be2ca8aa9aad5a35ca8609616ab8a932": "psb",
    "24de397c9f558b9c45da1aa32e8fb43c3ad567e497fc9aaced42b3ca68cf18a5": "bchpb",
    "3e3d4db937b1b238589c253a423d8f4a24d66f29eab1852c01df818e462a2f24": "raif",
    "085972a6486f548040a1e15e8cab81fddcb021993c6681e75b4815eaf01497af": "raif",
    "ebacacce01ca9c6e2dae1257b0eb9760cd0dde5fa243f6bc46762862982f3bc9": "raif",
    "925c7b31799c340ff270f71ada6964e2e83253f3ea79faefdda461a535446582": "rocket",
    "e0def455492d98a8ef98aadcd62cec9bb6919f22ce9b795771aff74b0b1ff41b": "sovkom",
    "48d2232faa0fa17570fe2aea8166a770aa5af9c1c1022d11646fa0bfce66311e": "uralsib",
    "013be8ac2f495e4f65d5df3b7c694a41922ea35db6b55c69f1b19b849a886b7d": "yandex",
    "03ab692a38bf133fcd9442e0118c5975ad514b72fe88d91fbdd8b2a96193ff25": "yandex",
    "f3b7d17b3e44e39fe03d9aacc7402ea093dff660f4595e85aae3e40f26adfbb7": "yandex",
}


def _collect_pdfs() -> list[str]:
    pdfs: list[str] = []
    for root, _, files in os.walk(CORPUS):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdfs.append(os.path.join(root, f))
    return sorted(pdfs)


def main() -> int:
    pdfs = _collect_pdfs()
    print(f"Corpus: {len(pdfs)} PDF")

    ok_all = 0
    ok_unique: set[str] = set()
    failures: list[str] = []

    for path in pdfs:
        data = open(path, "rb").read()
        h = hashlib.sha256(data).hexdigest()
        bank = SHA_BANK.get(h)
        name = os.path.basename(path)
        if not bank:
            failures.append(f"{name} | unknown SHA {h[:12]}")
            continue
        v1 = analyze_v1(data, bank)
        if v1.get("verdict") == "ЧИСТО":
            ok_all += 1
            ok_unique.add(h)
        else:
            failures.append(
                f"{name} | {bank} | flags={v1.get('flags')}"
            )

    print(f"Sparse9 v1:  {ok_all}/{len(pdfs)} ЧИСТО")
    print(f"Unique SHA:  {len(ok_unique)}/15 ЧИСТО")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("REG-O-001 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
