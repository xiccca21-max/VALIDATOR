"""K-GLOBAL-TEXT-GLYPH-RENDER-MISMATCH-001 — all banks, before bank checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO

from .pdf_forensics import (
    _cmap_unicode,
    _extract_font_programs,
    _glyph_outline_hash,
    _parse_W_arrays,
)
from .structure import content_stream_bytes, validate_pdf_structure

try:
    import fitz
except ImportError:
    fitz = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None

RULE_ID = "K-GLOBAL-TEXT-GLYPH-RENDER-MISMATCH-001"
HARD_CODE = "GLOBAL_TEXT_GLYPH_RENDER_MISMATCH"

_INVISIBLE = frozenset(
    " \t\n\r\u00a0\u200b\u200c\u200d\u200e\u200f"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"
)
_VISIBLE_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё.,:;+\-()%№]")

_CRITICAL_LABELS: dict[str, tuple[str, ...]] = {
    "amount": ("итого", "сумма", "сумма перевода", "сумма операции"),
    "date": ("дата", "дата операции", "дата и время"),
    "status": ("статус", "статус операции", "состояние"),
    "sender": ("отправитель", "ф.и.о. отправителя", "плательщик", "фио отправителя"),
    "receiver": ("получатель", "фио получателя", "кому"),
    "phone": ("телефон получателя", "номер телефона"),
    "bank": ("банк получателя", "банк зачисления"),
    "card": ("карта", "счет", "счёт", "реквизиты карты"),
    "operation_id": ("идентификатор операции", "id операции", "номер операции"),
    "receipt_no": ("номер квитанции", "квитанция", "rrn"),
}


@dataclass
class GlyphEvidence:
    page: int
    field: str
    char: str
    unicode: str
    cid: int
    gid: int
    font: str
    parser_text: str
    fitz_width: float
    glyf_empty: bool
    hmtx_advance: int
    detail: str


@dataclass
class GlobalTextGlyphResult:
    hard: bool = False
    flags: list[str] = field(default_factory=list)
    evidences: list[GlyphEvidence] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def _glyph_metrics(tt_data: bytes, gid: int) -> tuple[bool, int, int]:
    """Return (empty_glyph, contours, hmtx_advance)."""
    if not TTFont:
        return False, 0, 500
    try:
        tt = TTFont(BytesIO(tt_data))
        order = tt.getGlyphOrder()
        if gid < 0 or gid >= len(order):
            return True, 0, 0
        gname = order[gid]
        g = tt["glyf"][gname]
        try:
            g.expand(tt["glyf"])
        except Exception:
            pass
        contours = int(getattr(g, "numberOfContours", 0) or 0)
        coords = getattr(g, "coordinates", None) or []
        empty = contours <= 0 and not coords and not getattr(g, "isComposite", lambda: False)()
        adv = int(tt["hmtx"][gname][0]) if "hmtx" in tt else 500
        return empty, contours, adv
    except Exception:
        return False, 0, 500


def _classify_field(label: str) -> str:
    low = re.sub(r"\s+", " ", (label or "").strip().lower())
    for field_name, keys in _CRITICAL_LABELS.items():
        if any(k in low for k in keys):
            return field_name
    return ""


def _extract_field_values(pdf_bytes: bytes) -> list[tuple[str, str, float]]:
    """(field_kind, value_text, y) from fitz dict label→value pairs."""
    if not fitz:
        return []
    out: list[tuple[str, str, float]] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_dict = doc[0].get_text("dict") if doc.page_count else {}
        doc.close()
    except Exception:
        return []
    lines_meta: list[tuple[str, float]] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in line.get("spans", [])).strip()
            if not txt:
                continue
            bbox = line.get("bbox") or (0, 0, 0, 0)
            lines_meta.append((txt, float(bbox[1])))
    for i, (txt, y) in enumerate(lines_meta):
        if not txt.endswith(":"):
            continue
        label = txt[:-1]
        field = _classify_field(label)
        if not field:
            continue
        for j in range(i + 1, min(i + 4, len(lines_meta))):
            val, vy = lines_meta[j]
            if val.endswith(":"):
                break
            if val and not _is_bank_footer(val):
                out.append((field, val, vy))
                break
    return out


def _is_bank_footer(text: str) -> bool:
    low = text.lower()
    return any(x in low for x in ("gazprombank", "mailbox@", "www.", "e-mail:"))


def _fitz_chars(pdf_bytes: bytes) -> list[dict]:
    if not fitz:
        return []
    chars: list[dict] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for pno, page in enumerate(doc):
            try:
                trace = page.get_texttrace()
            except Exception:
                continue
            for span in trace:
                font = span.get("font", "")
                for ch in span.get("chars", []):
                    try:
                        ucs, gid, *_rest = ch
                        ox, oy, ex, ey = ch[3], ch[4], ch[5], ch[6]
                    except Exception:
                        continue
                    if ucs <= 0:
                        continue
                    chars.append({
                        "page": pno,
                        "char": chr(ucs),
                        "gid": int(gid),
                        "font": font,
                        "y": float(oy),
                        "width": max(0.0, float(ex) - float(ox)),
                    })
        doc.close()
    except Exception:
        pass
    return chars


def _match_char_in_field(
    field_text: str,
    field_y: float,
    target: str,
    chars: list[dict],
    *,
    y_tol: float = 4.0,
) -> dict | None:
    idx = field_text.find(target)
    if idx < 0:
        return None
    prefix = field_text[:idx + 1]
    for ch in chars:
        if ch["char"] != target:
            continue
        if abs(ch["y"] - field_y) <= y_tol:
            return ch
    for ch in chars:
        if ch["char"] == target and abs(ch["y"] - field_y) <= y_tol * 2:
            return ch
    return None


def run_global_text_glyph_render(
    pdf_bytes: bytes,
    *,
    text: str = "",
) -> GlobalTextGlyphResult:
    """
    Detect parser-visible characters whose embedded glyph does not render.

    Hard ФЕЙК only when:
    - symbol is in a critical receipt field;
    - mapping resolves to visible letter/digit/punctuation;
    - fitz renderer and glyph program both confirm missing/empty outline.
    """
    out = GlobalTextGlyphResult()
    if not pdf_bytes or not fitz or not TTFont:
        out.stats["skipped"] = "fitz_or_fonttools_missing"
        return out

    struct = validate_pdf_structure(pdf_bytes)
    if struct.codes:
        out.stats["structure_issues"] = struct.codes[:3]

    if not text:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = doc[0].get_text() if doc.page_count else ""
            doc.close()
        except Exception:
            text = ""

    cid_map, _ = _cmap_unicode(pdf_bytes)
    widths = _parse_W_arrays(pdf_bytes)
    fonts = _extract_font_programs(pdf_bytes)
    tt_data = fonts[0] if fonts else b""
    content = content_stream_bytes(pdf_bytes) or b""

    field_values = _extract_field_values(pdf_bytes)
    fitz_chars = _fitz_chars(pdf_bytes)
    out.stats["critical_fields"] = len(field_values)
    out.stats["fitz_chars"] = len(fitz_chars)
    out.stats["content_len"] = len(content)

    for field_kind, value, y in field_values:
        if field_kind in ("phone",) and _is_bank_footer(value):
            continue
        for ch in value:
            if ch in _INVISIBLE or not _VISIBLE_RE.match(ch):
                continue
            meta = _match_char_in_field(value, y, ch, fitz_chars)
            if not meta:
                continue
            gid = meta["gid"]
            fitz_invisible = meta["width"] < 0.35
            glyf_empty, contours, hmtx_adv = _glyph_metrics(tt_data, gid) if tt_data else (False, 1, 500)
            raw_invisible = glyf_empty or hmtx_adv <= 0
            if not (fitz_invisible and raw_invisible):
                continue
            cid_guess = next((c for c, u in cid_map.items() if u == ch), -1)
            w_val = widths.get(cid_guess, 0) if cid_guess >= 0 else 0
            detail = (
                f"rule_id={RULE_ID}; page={meta['page']}; field={field_kind}; "
                f"char={ch!r}; unicode=U+{ord(ch):04X}; CID={cid_guess}; GID={gid}; "
                f"font={meta['font']}; parser={value!r}; fitz_width={meta['width']:.3f}; "
                f"contours={contours}; hmtx={hmtx_adv}; /W={w_val}; "
                f"renderer_a=fitz_bbox; renderer_b=glyf+hmtx"
            )
            ev = GlyphEvidence(
                page=meta["page"],
                field=field_kind,
                char=ch,
                unicode=f"U+{ord(ch):04X}",
                cid=cid_guess,
                gid=gid,
                font=meta["font"],
                parser_text=value,
                fitz_width=meta["width"],
                glyf_empty=glyf_empty,
                hmtx_advance=hmtx_adv,
                detail=detail,
            )
            out.evidences.append(ev)
            out.hard = True
            out.flags.append(f"[{HARD_CODE}] {detail}")
            break
        if out.hard:
            break

    out.stats["mismatch_count"] = len(out.evidences)
    return out
