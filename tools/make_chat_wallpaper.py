#!/usr/bin/env python3
"""Обои для TG-чата: PROTON по диагонали, пиксельный стиль."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 1080, 1920
PIXEL = 20  # масштаб одного «пикселя» шрифта

# 7-строчный пиксельный шрифт (1 = закрашен)
_GLYPHS: dict[str, list[str]] = {
    "P": [
        "1111100",
        "1000100",
        "1000100",
        "1111100",
        "1000000",
        "1000000",
        "1000000",
    ],
    "R": [
        "1111100",
        "1000100",
        "1000100",
        "1111000",
        "1001000",
        "1000100",
        "1000010",
    ],
    "O": [
        "0111000",
        "1000100",
        "1000100",
        "1000100",
        "1000100",
        "1000100",
        "0111000",
    ],
    "T": [
        "1111111",
        "0011100",
        "0011100",
        "0011100",
        "0011100",
        "0011100",
        "0011100",
    ],
    "N": [
        "1000001",
        "1100001",
        "1010001",
        "1001001",
        "1000101",
        "1000011",
        "1000001",
    ],
}


def _noise_bg() -> Image.Image:
    img = Image.new("RGB", (W, H), (252, 252, 252))
    px = img.load()
    random.seed(42)
    for y in range(H):
        for x in range(W):
            if random.random() < 0.08:
                v = random.choice((235, 240, 245, 248))
                px[x, y] = (v, v, v)
    return img


def _draw_glyph(
    draw: ImageDraw.ImageDraw,
    glyph: list[str],
    ox: int,
    oy: int,
    color: tuple[int, int, int] = (0, 0, 0),
) -> tuple[int, int, int, int]:
    gh, gw = len(glyph), len(glyph[0])
    for row, line in enumerate(glyph):
        for col, ch in enumerate(line):
            if ch == "1":
                x1 = ox + col * PIXEL
                y1 = oy + row * PIXEL
                draw.rectangle(
                    [x1, y1, x1 + PIXEL - 1, y1 + PIXEL - 1],
                    fill=color,
                )
    return ox, oy, ox + gw * PIXEL, oy + gh * PIXEL


def main() -> None:
    img = _noise_bg()
    draw = ImageDraw.Draw(img)

    word = "PROTON"
    # Диагональ: верх (P) — левее и выше, низ (N) — правее и ниже
    # 6 букв на всю высоту с небольшими отступами
    margin_top, margin_bottom = 40, 40
    usable_h = H - margin_top - margin_bottom
    step_y = usable_h / (len(word) - 1) if len(word) > 1 else 0

    # Диагональ: верх (P) левее, низ (N) правее — на всю высоту
    x_start = 480
    x_end = 950
    step_x = (x_end - x_start) / (len(word) - 1) if len(word) > 1 else 0

    glyph_h = len(_GLYPHS["P"]) * PIXEL
    glyph_w = max(len(g) for g in _GLYPHS.values()) * PIXEL

    for i, ch in enumerate(word):
        cx = int(x_start + i * step_x)
        cy = int(margin_top + i * step_y - glyph_h // 2)
        # Центрируем букву в точке диагонали
        _draw_glyph(draw, _GLYPHS[ch], cx - glyph_w // 2, cy)

    out = Path(__file__).resolve().parents[1] / "assets" / "proton_chat_wallpaper_v2.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"Saved {out} ({W}x{H})")


if __name__ == "__main__":
    main()
