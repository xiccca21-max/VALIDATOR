"""PDF size breakdown: originals vs Jasper t01."""
from __future__ import annotations

import re
from pathlib import Path

import fitz

FILES = [
    Path(r"c:\Users\fanis\Downloads\Receipt (23).pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\templates\T_sbp_original.pdf"),
    Path(r"c:\Users\fanis\OneDrive\Desktop\ВАЖНО!!!\готовые проекты\BOT UMBRAL\_test5_jasper\t01_55000_Сбер.pdf"),
]


def breakdown(path: Path) -> dict:
    b = path.read_bytes()
    doc = fitz.open(path)
    n = doc.xref_length()
    fonts_ff2: list[tuple[str, int]] = []
    stream_sizes: list[int] = []
    img_bytes = 0
    for i in range(1, n):
        o = doc.xref_object(i)
        if "/FontFile2" in o:
            m = re.search(r"/FontFile2\s+(\d+)", o)
            if m:
                ff = doc.xref_stream(int(m.group(1)))
                bf = re.search(r"/BaseFont\s*/([^\s/>]+)", o)
                fonts_ff2.append((bf.group(1) if bf else "?", len(ff)))
        if "/Subtype" in o and "Image" in o:
            try:
                img_bytes += len(doc.xref_stream(i))
            except Exception:
                pass
        try:
            raw = doc.xref_stream(i)
            if raw:
                stream_sizes.append(len(raw))
        except Exception:
            pass
    cs = sum(len(doc.xref_stream(x)) for x in doc[0].get_contents())
    doc.close()
    return {
        "total": len(b),
        "xref": n,
        "fonts_ff2": fonts_ff2,
        "content": cs,
        "img": img_bytes,
        "font_total": sum(x[1] for x in fonts_ff2),
        "all_streams": sum(stream_sizes),
    }


def main() -> None:
    for p in FILES:
        if not p.exists():
            print(f"MISSING {p}")
            continue
        d = breakdown(p)
        print("=" * 60)
        print(f"{p.name}: {d['total']:,} B ({d['total']/1024:.1f} KB)  xref={d['xref']}")
        print(f"  page content:     {d['content']:,} B")
        print(f"  images (raw):   {d['img']:,} B")
        print(f"  FontFile2 sum:  {d['font_total']:,} B")
        for bf, sz in d["fonts_ff2"]:
            print(f"    {bf}: {sz:,} B")
        print(f"  all streams:    {d['all_streams']:,} B")


if __name__ == "__main__":
    main()
