"""Regression: embedded_font_reassembly_forensics — 190 originals CLEAN, 10 fakes FAKE."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from detector.alfa import analyze as alfa_analyze  # noqa: E402
from detector.sber import analyze as sber_analyze  # noqa: E402
from detector.tbank import analyze as tbank_analyze  # noqa: E402

ALFA_CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
SBER_CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\сбер")
TBANK_CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\т банк")
FAKE_DIR = Path(r"C:\Users\fanis\OneDrive\Desktop\фейки хорошие")

REBUILD_PREFIXES = (
    "ALFA_REBUILD_",
    "SBER_REBUILD_",
    "TBANK_REBUILD_",
)


def _codes(r: dict) -> set[str]:
    out: set[str] = set()
    for f in r.get("flags") or []:
        if isinstance(f, str) and f.startswith("[") and "]" in f:
            out.add(f[1 : f.index("]")])
    return out


def _rebuild_codes(codes: set[str]) -> list[str]:
    return sorted(c for c in codes if c.startswith(REBUILD_PREFIXES))


def scan_corpus(name: str, folder: Path, analyze, limit: int | None = None) -> tuple[int, int, list[str]]:
    pdfs = sorted(folder.glob("*.pdf"))
    if limit:
        pdfs = pdfs[:limit]
    dirty: list[str] = []
    clean = 0
    for p in pdfs:
        r = analyze(p.read_bytes())
        v = r.get("verdict")
        codes = _codes(r)
        rebuild = _rebuild_codes(codes)
        if v == "ЧИСТО" and not rebuild:
            clean += 1
        elif v == "ЧИСТО" and rebuild:
            dirty.append(f"{p.name}: CLEAN but rebuild={rebuild}")
        else:
            dirty.append(f"{p.name}: {v} rebuild={rebuild} flags={sorted(codes)[:4]}")
    return len(pdfs), clean, dirty


def main() -> int:
    print("=== ORIGINALS ===")
    a_n, a_c, a_d = scan_corpus("alfa", ALFA_CORPUS, alfa_analyze)
    # Prefer first 40 if 41 present
    if a_n > 40:
        a_n, a_c, a_d = scan_corpus("alfa", ALFA_CORPUS, alfa_analyze, limit=40)
    print(f"alfa {a_c}/{a_n} clean")
    for line in a_d[:10]:
        print(" ", line)

    s_n, s_c, s_d = scan_corpus("sber", SBER_CORPUS, sber_analyze)
    print(f"sber {s_c}/{s_n} clean")
    for line in s_d[:10]:
        print(" ", line)

    t_n, t_c, t_d = scan_corpus("tbank", TBANK_CORPUS, tbank_analyze)
    print(f"tbank {t_c}/{t_n} clean")
    for line in t_d[:10]:
        print(" ", line)

    print("\n=== FAKES (10 bank fakes, skip yandex) ===")
    fakes = [
        p for p in sorted(FAKE_DIR.glob("*.pdf"))
        if "яндекс" not in p.name.lower()
    ][:10]
    fake_ok = 0
    for p in fakes:
        # route by name/content
        if "alfa" in p.name.lower():
            r = alfa_analyze(p.read_bytes())
            bank = "alfa"
        else:
            r = tbank_analyze(p.read_bytes())
            bank = "tbank"
        v = r.get("verdict")
        rebuild = _rebuild_codes(_codes(r))
        ok = v == "ФЕЙК"
        fake_ok += int(ok)
        print(f"{'OK' if ok else 'FAIL'} {p.name} [{bank}] {v} rebuild={rebuild[:5]}")

    # also sber fakes if present
    sber_fakes = [
        Path(r"C:\Users\fanis\Downloads\Telegram Desktop\sber_sbp_211001.pdf"),
        Path(r"C:\Users\fanis\Downloads\Telegram Desktop\sber_sbp_202951.pdf"),
    ]
    for p in sber_fakes:
        if not p.is_file():
            continue
        r = sber_analyze(p.read_bytes())
        print(f"SBER_FAKE {p.name} {r.get('verdict')} rebuild={_rebuild_codes(_codes(r))[:5]}")

    total_orig = a_n + s_n + t_n
    total_clean = a_c + s_c + t_c
    print(f"\nORIGINALS {total_clean}/{total_orig}")
    print(f"FAKES {fake_ok}/{len(fakes)}")
    ok = total_clean == total_orig and fake_ok == len(fakes) and total_orig >= 190
    # 40+22+128 = 190
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
