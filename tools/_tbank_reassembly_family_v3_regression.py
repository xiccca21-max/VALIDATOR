"""Regression: TBANK_REASSEMBLY_FAMILY_V3 live module."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import analyze  # noqa: E402
from detector.tbank_reassembly_family_v3 import (  # noqa: E402
    CODE_CMAP,
    CODE_FAMILY,
    CODE_W,
    extract_used_cids,
    profile_gate,
    resolve_font_graph,
    run_tbank_reassembly_family_v3_stack,
)
from detector.corpus_profiles import CHANNEL_SBP, detect_receipt_channel  # noqa: E402

try:
    import fitz
except ImportError:
    fitz = None

TD = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
CORP = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")


def codes(result: dict) -> list[str]:
    out: list[str] = []
    for f in result.get("flags") or []:
        if isinstance(f, str) and f.startswith("[") and "]" in f:
            out.append(f[1:f.index("]")])
    return out


def main() -> int:
    fakes = []
    for p in TD.glob("receipt_21.07.2026 (*).pdf"):
        n = int(re.search(r"\((\d+)\)", p.name).group(1))
        if 6 <= n <= 20:
            fakes.append((n, p))
    fakes.sort()
    print(f"fakes={len(fakes)}")

    fake_detected = 0
    fake_missed = 0
    for n, p in fakes:
        r = analyze(p.read_bytes())
        cs = codes(r)
        has = CODE_FAMILY in cs
        ok = r.get("verdict") == "ФЕЙК" and has
        if ok:
            fake_detected += 1
        else:
            fake_missed += 1
            print("MISS", p.name, r.get("verdict"), cs[:8])
        if n == 17:
            need = {CODE_CMAP, CODE_W}
            print("receipt17 codes", [c for c in cs if "CMAP" in c or "W_ARRAY" in c or "FAMILY" in c or "BIJECTION" in c])
            if not need <= set(cs):
                print("FAIL receipt17 missing", need - set(cs))
                fake_missed += 1

    # extras on 17 via stack
    pdf17 = (TD / "receipt_21.07.2026 (17).pdf").read_bytes()
    st = run_tbank_reassembly_family_v3_stack(pdf17)
    print("17 extras F1", st.stats.get("F1_extra_mapped"), "F2", st.stats.get("F2_extra_mapped"))
    print("17 font/stream", st.stats.get("font_signature"), st.stats.get("stream_signature"))

    sbp_fp = 0
    sbp_n = 0
    non_sbp_gate = 0
    for p in sorted(CORP.glob("*.pdf")):
        pdf = p.read_bytes()
        if not fitz:
            break
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(pg.get_text() for pg in doc)
        doc.close()
        gate_ok, gs = profile_gate(pdf, text=text)
        ch = gs.get("channel")
        is_sbp = ch == CHANNEL_SBP or "идентификатор операции" in text.lower()
        if not is_sbp:
            if not gate_ok:
                non_sbp_gate += 1
            continue
        sbp_n += 1
        r = analyze(pdf)
        cs = codes(r)
        new = [c for c in cs if c in {
            CODE_FAMILY, CODE_CMAP, CODE_W,
            "TBANK_CID_SERIALIZATION_BIJECTION_VIOLATION",
            "TBANK_FONT_SUBSET_EXACT_CLOSURE",
            "TBANK_W_TTF_ADVANCE_MISMATCH",
        }]
        if new:
            sbp_fp += 1
            print("FP", p.name, r.get("verdict"), new)
        if sbp_n % 10 == 0:
            print(f"... sbp {sbp_n} fp={sbp_fp}")

    print(
        f"RESULT fake_detected={fake_detected} fake_missed={fake_missed} "
        f"sbp_n={sbp_n} sbp_fp={sbp_fp} non_sbp_skipped_gate={non_sbp_gate}"
    )
    assert fake_detected == 15, fake_detected
    assert fake_missed == 0, fake_missed
    assert sbp_fp == 0, sbp_fp
    print("ACCEPTANCE OK validator live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
