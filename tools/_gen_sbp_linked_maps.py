"""One-off: print linked SBP tuple maps from corpus."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz

from detector.sbp_cipher import extract_sbp_opid

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
PROFILES = [("G1", "00117"), ("00", "00116"), ("B1", "00117"), ("B0", "00116")]


def main() -> None:
    triple: dict[tuple[str, str], dict[tuple[str, str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    quad: dict[tuple[str, str], set[tuple[str, str, str, str]]] = defaultdict(set)
    for p in CORPUS.glob("*.pdf"):
        doc = fitz.open(p)
        text = doc[0].get_text()
        doc.close()
        opid = extract_sbp_opid(text)
        if not opid:
            continue
        prof = (opid[17:19], opid[22:27])
        triple[prof][(opid[14], opid[19:22], opid[26:32])].add(opid[15])
        quad[prof].add((opid[15], opid[14], opid[19:22], opid[26:32]))

    for prof in PROFILES:
        print(f"    {prof!r}: {{")
        print('        "corpus_n": ...,')
        print('        "triple_control": {')
        for tr, ctrls in sorted(triple[prof].items()):
            if len(ctrls) == 1:
                c = next(iter(ctrls))
                print(f"            {tr!r}: {c!r},")
        print("        },")
        print('        "linked_tuples": frozenset({')
        for q in sorted(quad[prof]):
            print(f"            {q!r},")
        print("        }),")
        print("    },")


if __name__ == "__main__":
    main()
