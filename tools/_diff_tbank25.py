"""Compare tbank_all25 fakes vs genuine SBP originals."""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.structure import content_skeleton_hash
from detector.corpus_profiles import detect_receipt_channel
from detector.tbank import content_stream_bytes, _decoded_content_len, _page_dims
from detector.ff2_pool import _load_corpus, extract_ff2_fingerprints
from detector.sbp_cipher import validate_nspk_sbp_cipher, extract_sbp_opid
from detector.tbank_font_render import run_font_render_forgery_check
from detector.render_fingerprint import run_render_row_check
from detector.tbank_corpus_spec import run_tbank_corpus_spec_checks

FAKE_DIR = Path(r"C:\Users\fanis\OneDrive\Desktop\samaya-ohuenaya-versiya\output\tbank_all25\sbp")
ORIG_DIR = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")


def metrics(path: Path) -> dict:
    b = path.read_bytes()
    doc = fitz.open(path)
    text = doc[0].get_text()
    meta = dict(doc.metadata or {})
    doc.close()
    _, page_h = _page_dims(b)
    dec = _decoded_content_len(b)
    sk = content_skeleton_hash(b)
    fps = extract_ff2_fingerprints(b)
    corpus = _load_corpus()
    ff2_unknown = []
    for layer in ("F1", "F2", "F3"):
        h = fps[layer]["sha256_16"]
        if h not in set(corpus.get("layers", {}).get(layer, [])):
            ff2_unknown.append(layer)
    opid = extract_sbp_opid(text)
    cipher = [f.code for f in validate_nspk_sbp_cipher(opid or "", text).flags]
    fr_fake, fr_det = run_font_render_forgery_check(b, text)
    rb, rt, rd = run_render_row_check(b)
    cs = run_tbank_corpus_spec_checks(b, text=text, meta=meta)
    hard = [f.code for f in cs.flags if f.hard]
    soft = [f.code for f in cs.flags if not f.hard]
    # text fields
    bank_line = ""
    for ln in text.splitlines():
        if any(x in ln for x in ("Сбер", "Альф", "ВТБ", "Райф", "Т-Банк", "Тинькоф")):
            if "банк" in ln.lower() or "Банк" in ln:
                bank_line = ln.strip()
    return {
        "name": path.name,
        "size": len(b),
        "page_h": page_h,
        "dec": dec,
        "sk": sk,
        "ff2_unknown": ff2_unknown,
        "ff2": {k: fps[k]["sha256_16"] for k in ("F1", "F2", "F3")},
        "opid": opid,
        "cipher": cipher,
        "fr_fake": fr_fake,
        "render_bad": rb,
        "render_total": rt,
        "corpus_hard": hard,
        "corpus_soft": soft[:4],
        "bank_line": bank_line[:50],
        "keywords": meta.get("keywords", ""),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    fakes = sorted(FAKE_DIR.glob("*.pdf"))
    origs = sorted(p for p in ORIG_DIR.glob("*.pdf") if "сбп" in p.name.lower())

    for label, paths in [("FAKE", fakes), ("ORIG SBP", origs)]:
        print(f"\n{'='*70}\n{label} n={len(paths)}\n{'='*70}")
        for p in paths:
            m = metrics(p)
            print(
                f"{m['name'][:26]:26s} sz={m['size']/1024:5.1f}K "
                f"h={m['page_h']} dec={m['dec']:5d} sk={str(m['sk'])[:10]}"
            )
            print(f"  ff2_unk={m['ff2_unknown']} cipher={m['cipher']}")
            print(f"  fr_fake={m['fr_fake']} render={m['render_bad']}/{m['render_total']}")
            print(f"  corpus_hard={m['corpus_hard']} soft={m['corpus_soft']}")
            print(f"  bank={m['bank_line']!r} kw={str(m['keywords'])[:40]}")


if __name__ == "__main__":
    main()
