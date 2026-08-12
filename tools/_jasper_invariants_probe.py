"""Find invariant structural diffs: generator fakes vs bank originals (no corpus)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from detector.corpus_profiles import detect_receipt_channel
from detector.ff2_pool import extract_ff2_fingerprints, _extract_fontfile2
from detector.font_authenticity import _table_digest, _stable_table_hashes, _tables
from detector.structure import content_stream_bytes, find_streams, content_skeleton_hash
from detector.tbank import (
    _creation_eq_operation,
    _foreign_width_array,
    _keywords_creation_mismatch,
    _bfchar_in_tounicode,
)
from detector.tbank_corpus_spec import _count_ops, _shell_counts, _page_dims

FAKE_ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\samaya-ohuenaya-versiya\output\tbank_all25")
ORIG = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")


def pdf_text(b: bytes) -> str:
    import fitz
    doc = fitz.open(stream=b, filetype="pdf")
    t = doc[0].get_text()
    doc.close()
    return t


def stream_zlib_header(b: bytes) -> str | None:
    for raw, dec in find_streams(b):
        if dec and b"Tj" in dec and len(dec) > 500:
            return raw[:2].hex() if len(raw) >= 2 else None
    return None


def w_array_style(b: bytes) -> dict:
    """How /W width arrays are serialized in font objects."""
    from detector.tbank_corpus_spec import _w_raw_blob
    from detector.font_layers import _font_objects
    fonts, _ = _font_objects(b)
    out = {}
    for key in ("F1", "F2", "F3"):
        fo = fonts.get(key) or {}
        blob = fo.get("blob") or b""
        w = _w_raw_blob(blob)
        if not w:
            continue
        out[key] = {
            "len": len(w),
            "has_space_after_bracket": bool(re.search(rb"/W\s*\[\s", w)),
            "newline_after_open": b"/W\n" in blob or b"/W\r" in blob,
            "compact": b"/W[" in blob.replace(b" ", b"")[:20],
        }
    return out


def content_stream_style(b: bytes) -> dict:
    cs = content_stream_bytes(b) or b""
    return {
        "len": len(cs),
        "bt_et": (cs.count(b"BT"), cs.count(b"ET")),
        "tj_paren": len(re.findall(rb"\([^)]*\)\s*Tj", cs)),
        "tj_hex": len(re.findall(rb"<[0-9A-Fa-f]*>\s*Tj", cs)),
        "tm_count": len(re.findall(rb"\bTm\b", cs)),
        "leading_space_before_bt": bool(re.search(rb"\sBT", cs[:80])),
        "double_space": b"  " in cs[:200],
    }


def id_style(b: bytes) -> dict:
    m = re.search(rb"/ID\s*\[\s*<([^>]+)>\s*<([^>]+)>\s*\]", b)
    if not m:
        return {}
    a, b2 = m.group(1).decode(), m.group(2).decode()
    return {
        "id1_len": len(a),
        "id2_len": len(b2),
        "id1_lower": a == a.lower(),
        "id2_lower": b2 == b2.lower(),
        "ids_equal": a == b2,
    }


def probe_group(paths: list[Path], label: str) -> None:
    print(f"\n{'='*60}\n{label} n={len(paths)}\n{'='*60}")
    zlib_h = Counter()
    id_lower = Counter()
    ids_eq = Counter()
    bt_et = Counter()
    w_space = Counter()
    f1_digest = Counter()
    invariants = defaultdict(int)

    for p in paths:
        b = p.read_bytes()
        t = pdf_text(b)
        zh = stream_zlib_header(b)
        if zh:
            zlib_h[zh] += 1
        ids = id_style(b)
        if ids.get("id1_lower"):
            id_lower["all_lower"] += 1
        if ids.get("ids_equal"):
            ids_eq["equal"] += 1
        cs = content_stream_style(b)
        bt_et[cs["bt_et"]] += 1
        w = w_array_style(b)
        for k, v in w.items():
            if v.get("has_space_after_bracket"):
                w_space[f"{k}_pretty"] += 1
        ttf = _extract_fontfile2(b, "F1")
        if ttf:
            f1_digest[_table_digest(_stable_table_hashes(_tables(ttf)))] += 1
        if _foreign_width_array(b)[0]:
            invariants["foreign_width"] += 1
        if _bfchar_in_tounicode(b)[0]:
            invariants["bfchar"] += 1
        if _creation_eq_operation(b)[0]:
            invariants["creation_eq"] += 1
        if _keywords_creation_mismatch(b)[0]:
            invariants["keywords"] += 1

    print("zlib header top:", zlib_h.most_common(3))
    print("id all lowercase:", id_lower)
    print("id1==id2:", ids_eq)
    print("BT/ET pairs top:", bt_et.most_common(5))
    print("/W pretty-print:", dict(w_space))
    print("F1 stable digest unique:", len(f1_digest))
    print("invariant hits:", dict(invariants))


def main() -> None:
    fakes = sorted(FAKE_ROOT.rglob("*.pdf"))
    origs = sorted(ORIG.glob("*.pdf"))
    probe_group(fakes, "FAKES")
    probe_group(origs, "ORIGINALS")

    # pairwise diff signals that separate 100%
    print("\n--- SEPARATORS (fake-only vs orig-only) ---")
    fake_sk = {content_skeleton_hash(p.read_bytes()) for p in fakes}
    orig_sk = {content_skeleton_hash(p.read_bytes()) for p in origs}
    print("skeleton overlap fake∩orig:", len(fake_sk & orig_sk))

    fake_trips = set()
    orig_trips = set()
    for p in fakes:
        fp = extract_ff2_fingerprints(p.read_bytes())
        if fp:
            fake_trips.add(tuple(fp[l]["sha256_16"] for l in ("F1", "F2", "F3")))
    for p in origs:
        fp = extract_ff2_fingerprints(p.read_bytes())
        if fp:
            orig_trips.add(tuple(fp[l]["sha256_16"] for l in ("F1", "F2", "F3")))
    print("triplet overlap:", len(fake_trips & orig_trips))

    # content stream length per channel
    for ch_name in ("sbp", "card", "phone"):
        fake_lens = []
        orig_lens = []
        for p in fakes:
            b = p.read_bytes()
            if detect_receipt_channel(pdf_text(b)) == ch_name:
                fake_lens.append(len(content_stream_bytes(b) or b""))
        for p in origs:
            b = p.read_bytes()
            if detect_receipt_channel(pdf_text(b)) == ch_name:
                orig_lens.append(len(content_stream_bytes(b) or b""))
        if fake_lens or orig_lens:
            print(f"  {ch_name} cs_len fake {min(fake_lens) if fake_lens else '-'}..{max(fake_lens) if fake_lens else '-'} | orig {min(orig_lens) if orig_lens else '-'}..{max(orig_lens) if orig_lens else '-'}")


if __name__ == "__main__":
    main()
