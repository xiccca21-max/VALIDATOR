#!/usr/bin/env python3
"""Regression for K-TBANK-STREAM-SERIALIZER-001."""
from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.tbank import analyze
from detector.tbank_flate_profile import enumerate_flate_streams
from detector.tbank_stream_serializer import check_mixed_flate_serializer, profiles_table

CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
TOUGH = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026.pdf")
FAKE_ANCHOR = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026 (4).pdf")
MUT_DIR = ROOT / "tools" / "_mutations"


def mutate_selective_content(pdf_bytes: bytes, *, level: int = 9) -> bytes:
    """Recompress only page-content stream with Python zlib (non-Java profile)."""
    _OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.DOTALL)
    out = bytearray(pdf_bytes)
    for m in _OBJ.finditer(pdf_bytes):
        objn = int(m.group(1))
        body = m.group(3)
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            continue
        hdr = body[: sm.start()]
        start = sm.end()
        lm = re.search(rb"/Length\s+(\d+)", hdr)
        if not lm:
            continue
        ln = int(lm.group(1))
        raw_start = m.start(0) + sm.end()
        raw = pdf_bytes[raw_start : raw_start + ln]
        try:
            dec = zlib.decompress(raw)
        except Exception:
            continue
        if not (b"BT" in dec and (b"Tj" in dec or b"TJ" in dec) and b"Tm" in dec):
            continue
        new_raw = zlib.compress(dec, level)
        if new_raw == raw:
            continue
        old_chunk = pdf_bytes[raw_start : raw_start + ln]
        delta = len(new_raw) - ln
        new_chunk = new_raw
        pos = m.start(0)
        end_obj = pdf_bytes.find(b"endobj", raw_start + ln) + 6
        before = pdf_bytes[:raw_start]
        after = pdf_bytes[raw_start + ln :]
        patched = before + new_chunk + after
        patched = re.sub(
            rb"(/Length\s+)" + str(ln).encode() + rb"(\s)",
            rb"\g<1>" + str(len(new_raw)).encode() + rb"\2",
            patched[pos : pos + 400],
            count=1,
        )
        # simpler full replace on object body
        obj_blob = pdf_bytes[m.start(0) : end_obj]
        new_obj = obj_blob.replace(old_chunk, new_raw, 1)
        new_obj = re.sub(
            rb"/Length\s+\d+",
            f"/Length {len(new_raw)}".encode(),
            new_obj,
            count=1,
        )
        return pdf_bytes[: m.start(0)] + new_obj + pdf_bytes[end_obj:]
    return bytes(pdf_bytes)


def mutate_whole_document(pdf_bytes: bytes, *, level: int = 9) -> bytes:
    """Recompress ALL flate streams with Python zlib."""
    result = pdf_bytes
    for _ in range(12):
        nxt = mutate_selective_content(result, level=level)
        if nxt == result:
            break
        result = nxt
    # brute: replace each stream one pass
    _OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.DOTALL)
    out = bytearray(result)
    pdf = result
    parts: list[bytes] = []
    last = 0
    for m in _OBJ.finditer(pdf):
        body = m.group(3)
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            continue
        hdr = body[: sm.start()]
        raw_start = m.start(0) + sm.end()
        lm = re.search(rb"/Length\s+(\d+)", hdr)
        if not lm:
            continue
        ln = int(lm.group(1))
        raw = pdf[raw_start : raw_start + ln]
        if raw[:1] != b"\x78":
            continue
        try:
            dec = zlib.decompress(raw)
        except Exception:
            continue
        new_raw = zlib.compress(dec, level)
        if new_raw == raw:
            continue
        parts.append((m.start(0), raw_start, ln, new_raw))
    if not parts:
        return pdf
    rebuilt = bytearray(pdf)
    offset = 0
    for obj_start, raw_start, ln, new_raw in parts:
        rs = raw_start + offset
        rebuilt[rs : rs + ln] = new_raw + b" " * max(0, ln - len(new_raw))
        if len(new_raw) != ln:
            # patch length in object header
            hdr_zone = bytes(rebuilt[obj_start + offset : rs])
            new_hdr = re.sub(
                rb"/Length\s+\d+",
                f"/Length {len(new_raw)}".encode(),
                hdr_zone,
                count=1,
            )
            rebuilt[obj_start + offset : rs] = new_hdr
            delta = len(new_raw) - ln
            rebuilt = rebuilt[: rs + len(new_raw)] + rebuilt[rs + ln :]
            offset += delta
    return bytes(rebuilt)


def print_stream_table(path: Path, label: str) -> None:
    print(f"\n=== {label}: {path.name} ===")
    if not path.exists():
        print("  MISSING")
        return
    b = path.read_bytes()
    profiles = enumerate_flate_streams(b)
    for row in profiles_table(profiles):
        print(
            f"  {row['object']:>6}  {row['role']:14}  "
            f"canonical={str(row['canonical_match']):5}  "
            f"actual={row['actual_hash']}  expected={row['expected_hash']}"
        )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("1. STREAM TABLE — anchor fake")
    print_stream_table(FAKE_ANCHOR, "FAKE anchor")
    if not FAKE_ANCHOR.exists() and TOUGH.exists():
        print("\n  (4).pdf not found — building selective mutation from tough sample")
        MUT_DIR.mkdir(exist_ok=True)
        base = TOUGH.read_bytes()
        sel = mutate_selective_content(base)
        sel_path = MUT_DIR / "mutation_selective_content.pdf"
        sel_path.write_bytes(sel)
        print_stream_table(sel_path, "MUTATION selective content")

    print("\n" + "=" * 60)
    print("2. CORPUS STATS (originals)")
    if CORPUS.exists():
        files = sorted(CORPUS.glob("*.pdf"))
        total_streams = mismatches = 0
        for p in files:
            for prof in enumerate_flate_streams(p.read_bytes()):
                total_streams += 1
                if not prof.canonical_match:
                    mismatches += 1
        unique_sha = len({p.read_bytes().__hash__() for p in files})
        print(f"  files: {len(files)}")
        print(f"  streams checked: {total_streams}")
        print(f"  canonical mismatches: {mismatches}")
        print(f"  FP via analyze: ", end="")
        fps = sum(1 for p in files if analyze(p.read_bytes())["verdict"] == "ФЕЙК")
        print(f"{fps}/{len(files)}")
    else:
        print("  corpus MISSING")

    print("\n" + "=" * 60)
    print("3. TOUGH SAMPLE (all streams canonical)")
    print_stream_table(TOUGH, "tough/original")

    print("\n" + "=" * 60)
    print("4. REGRESSION mutations")
    if TOUGH.exists():
        base = TOUGH.read_bytes()
        sel = mutate_selective_content(base)
        whole = mutate_whole_document(base)
        MUT_DIR.mkdir(exist_ok=True)
        (MUT_DIR / "mutation_selective.pdf").write_bytes(sel)
        (MUT_DIR / "mutation_whole.pdf").write_bytes(whole)
        for label, data in [
            ("selective content recompress", sel),
            ("whole-document recompress", whole),
        ]:
            r = analyze(data)
            sr = check_mixed_flate_serializer(data, shadow=False)
            print(f"  {label}: verdict={r['verdict']} serializer={sr.stats.get('verdict')}")
            if sr.hard_flags:
                print(f"    HARD: {sr.hard_flags[0][0]}")

    if FAKE_ANCHOR.exists():
        r = analyze(FAKE_ANCHOR.read_bytes())
        print(f"  anchor fake: verdict={r['verdict']} flags={r['flags'][:3]}")


if __name__ == "__main__":
    main()
