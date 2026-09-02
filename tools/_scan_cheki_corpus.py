"""Scan Desktop/чеки originals: report FAKE / wrong bank. No network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")

from detector import route  # noqa: E402

ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
SKIP = {"новая папка", "новая папка (2)", "шрифты", "чекки"}
MAX_PER_DIR = 8

FOLDER_BANK = {
    "альфа": "Альфа-Банк",
    "т банк": "Т-Банк",
    "сбер": "Сбербанк",
    "сбер_оригиналы_v2": "Сбербанк",
    "втб оригинал": "Банк ВТБ",
    "газпромбанк оригинал": "Газпромбанк",
    "озон чекии": "Ozon Банк",
    "промсвязьбанк": "Промсвязьбанк",
    "райф": "Райффайзенбанк",
    "отп банк": "ОТП Банк",
    "уралсиб": "Уралсиб",
    "яндекс банк": "Яндекс Банк",
    "совком": "Совкомбанк",
    "рокетбанк": "Рокетбанк",
    "бcпб банк": "Банк Санкт-Петербург",
    "вайлдберриз банк": "ВБ Банк",
    "мтс деньги": "МТС Деньги",
    "юмани банк": "ЮMoney",
    "русский стандарт": "Русский Стандарт",
    "точка банк": "Точка Банк",
}

problems: list[str] = []
ok = 0
scanned = 0

for folder in sorted(ROOT.iterdir() if ROOT.is_dir() else []):
    if not folder.is_dir():
        continue
    key = folder.name.casefold()
    if key in SKIP or folder.name.casefold() in SKIP:
        continue
    expected = FOLDER_BANK.get(key)
    if expected is None:
        print(f"SKIP unmapped {folder.name!r}")
        continue
    pdfs = sorted(folder.glob("*.pdf"))[:MAX_PER_DIR]
    print(f"--- {folder.name} expect={expected} n={len(pdfs)}")
    for path in pdfs:
        scanned += 1
        try:
            bank, result, _ = route(path.read_bytes())
        except Exception as exc:
            problems.append(f"CRASH {folder.name}/{path.name}: {exc}")
            print(" CRASH", path.name, exc)
            continue
        verdict = result.get("verdict")
        flags = result.get("flags") or []
        if verdict == "ЧИСТО" and bank == expected:
            ok += 1
            continue
        head = flags[:3]
        line = (
            f"{verdict} bank={bank!r} expected={expected!r} "
            f"{folder.name}/{path.name} flags={head}"
        )
        problems.append(line)
        print(" ", line)

print()
print(f"scanned={scanned} clean={ok} problems={len(problems)}")
for line in problems:
    print("P", line)
if problems:
    sys.exit(1)
