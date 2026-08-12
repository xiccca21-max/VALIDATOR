#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ шифра СБП-ID в чеках Альфа-Банка → alfa_sbp_extensions.json + отчёт."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from detector.alfa_profiles import extract_sbp_opid
from detector.alfa_sbp_cipher import validate_alfa_sbp_cipher

OUT_EXT = ROOT / "detector" / "alfa_sbp_extensions.json"
OUT_DOC = ROOT / "docs" / "alfa_sbp_cipher_analysis.md"
CHEKI = Path(os.environ.get("ALFA_DIR", Path.home() / "OneDrive" / "Desktop" / "чеки" / "альфа"))
EXTRA = [
    Path.home() / "Downloads" / "Unknown.pdf",
    Path.home() / "Downloads" / "Unknown1.pdf",
    Path.home() / "Downloads" / "Unknown3.pdf",
]
EXCLUDE: set[str] = set()


def _paths() -> list[Path]:
    paths: list[Path] = []
    if CHEKI.is_dir():
        paths.extend(sorted(CHEKI.glob("*.pdf")))
    paths.extend(p for p in EXTRA if p.is_file())
    return [p for p in paths if p.name not in EXCLUDE]


def main() -> None:
    paths = _paths()
    if not paths:
        print(f"No PDFs in {CHEKI}")
        sys.exit(1)

    samples: list[dict] = []
    tails: Counter[str] = Counter()
    cores: Counter[str] = Counter()
    fails = 0

    for p in paths:
        data = p.read_bytes()
        doc = fitz.open(stream=data, filetype="pdf")
        text = doc[0].get_text()
        doc.close()
        opid = extract_sbp_opid(text)
        if not opid:
            print(f"  skip (no SBP ID): {p.name}")
            continue
        cr = validate_alfa_sbp_cipher(opid, text)
        forgery = [f.code for f in cr.flags]
        if forgery:
            fails += 1
            print(f"  WARN {p.name}: {forgery}")
        tails[opid[27:32]] += 1
        cores[opid[22:27]] += 1
        samples.append({
            "file": p.name,
            "opid": opid,
            "tail": opid[27:32],
            "core": opid[22:27],
            "flags": forgery,
            **{k: cr.stats.get(k) for k in (
                "date_block", "hour", "minute", "second",
                "reference", "separator", "channel",
            )},
        })
        print(f"  OK {p.name} tail={opid[27:32]} ref={opid[11:17]}")

    ext_data = {
        "version": 1,
        "source_count": len(samples),
        "extensions": sorted(tails.keys()),
        "extension_counts": dict(tails),
        "core_suffixes": sorted(cores.keys()),
        "samples": samples,
    }
    OUT_EXT.write_text(json.dumps(ext_data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Анализ шифра СБП-ID (Альфа-Банк)",
        "",
        f"Эталонов с СБП-ID: **{len(samples)}**",
        "",
        "## Структура 32 символа",
        "",
        "```text",
        "[0]       A|B",
        "[1:5]     (год-2020)*1000 + день_года",
        "[5:7]     час UTC (МСК−3)",
        "[7:9]     минута",
        "[9:11]    секунда",
        "[11:17]   ссылка (символ [16] = '0')",
        "[17]      разделитель G|B",
        "[18:22]   код канала",
        "[22:27]   00117 / 00116",
        "[27:32]   хвост маршрута (5 цифр)",
        "```",
        "",
        "## Хвосты [27:32] в корпусе",
        "",
        "| Хвост | Чеков |",
        "|-------|-------|",
    ]
    for tail, cnt in tails.most_common():
        lines.append(f"| `{tail}` | {cnt} |")

    lines += [
        "",
        "## Ядро [22:27]",
        "",
        ", ".join(f"`{c}` ({n})" for c, n in cores.most_common()),
        "",
        f"Проверка cipher на корпусе: **{len(samples) - fails}/{len(samples)}** без forgery-флагов.",
        "",
        "Пересборка: `python tools/analyze_alfa_sbp_cipher.py`",
    ]
    OUT_DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {OUT_EXT} ({len(tails)} tails)")
    print(f"Wrote {OUT_DOC}")


if __name__ == "__main__":
    main()
