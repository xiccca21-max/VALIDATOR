"""Label-aware recipient-bank extraction shared by all bank engines.

issuer_bank          — bank that issued/formed the receipt (router/profile)
recipient_bank_*     — value of the PDF field «Банк получателя» / «…перевода»
sbp_route_profile    — internal SBP-ID routing data (never shown as recipient)

No SBP cores (00116/00117), issuer names, BIKs, filenames, or Gazprombank
fallback may populate recipient_bank_*.
"""

from __future__ import annotations

import re
from typing import Any

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None

# Longer labels first so "Банк получателя перевода" wins over "Банк получателя".
_RECIPIENT_BANK_LABELS: tuple[str, ...] = (
    "банк получателя перевода",
    "банк получателя",
    "банк-получатель",
    "банк зачисления",
    "наименование банка получателя",
)

_LABEL_NOISE = re.compile(r"[:\s\u00a0\u202f—–-]+")
_SPACE_RE = re.compile(r"[\s\u00a0\u202f]+")


def _norm_spaces(value: str) -> str:
    return _SPACE_RE.sub(" ", (value or "").replace("\xa0", " ").strip())


def _is_label_line(line: str, label: str) -> bool:
    compact = _LABEL_NOISE.sub("", (line or "").lower())
    target = _LABEL_NOISE.sub("", label.lower())
    return compact == target


def _looks_like_next_label(line: str) -> bool:
    low = (line or "").lower().strip()
    if not low:
        return True
    if low.endswith(":"):
        return True
    starters = (
        "получатель",
        "отправитель",
        "телефон",
        "фио",
        "сумма",
        "комиссия",
        "статус",
        "дата",
        "номер",
        "счёт",
        "счет",
        "карта",
        "идентификатор",
        "назначение",
        "сообщение",
        "банк отправителя",
        "банк получателя",
    )
    return any(low.startswith(s) for s in starters)


_AMOUNT_LIKE = re.compile(
    r"^(?:\d[\d\s\u00a0\u202f.,]*)\s*(?:₽|руб(?:[.]|ля|лей)?|RUB|RUR|р[.]?)$",
    re.I,
)


def _is_usable_bank_value(line: str) -> bool:
    value = _norm_spaces(line)
    if not value or _looks_like_next_label(value):
        return False
    if _AMOUNT_LIKE.match(value):
        return False
    if value in {".", "-", "—", "–"}:
        return False
    return True


def _from_plain_text(text: str) -> tuple[str, str]:
    """Return (raw, source) from line-oriented label lookup."""
    lines = [_norm_spaces(line) for line in (text or "").splitlines()]
    for label in _RECIPIENT_BANK_LABELS:
        for index, line in enumerate(lines):
            low = line.lower()
            if _is_label_line(line, label):
                for nxt in lines[index + 1 : index + 6]:
                    if not _is_usable_bank_value(nxt):
                        continue
                    return nxt, "explicit_pdf_field"
                continue
            if low.startswith(label):
                remainder = line[len(label) :].lstrip(" \t:.—–-")
                if remainder and _is_usable_bank_value(remainder):
                    return _norm_spaces(remainder), "explicit_pdf_field"
    return "", ""


def _from_coordinates(pdf_bytes: bytes) -> tuple[str, str]:
    """Prefer value to the right of the label; otherwise the next line below."""
    if fitz is None or not pdf_bytes:
        return "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return "", ""
    try:
        for page in doc:
            words = page.get_text("words") or []
            # words: x0, y0, x1, y1, word, block, line, word_no
            if not words:
                continue
            lines: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}
            for x0, y0, x1, y1, word, block, line, _wn in words:
                key = (int(block), int(line))
                lines.setdefault(key, []).append((float(x0), float(y0), float(x1), float(y1), str(word)))
            ordered_keys = sorted(
                lines,
                key=lambda key: (
                    min(item[1] for item in lines[key]),
                    min(item[0] for item in lines[key]),
                ),
            )
            rendered = []
            for key in ordered_keys:
                items = sorted(lines[key], key=lambda item: item[0])
                text = _norm_spaces(" ".join(item[4] for item in items))
                x0 = min(item[0] for item in items)
                y0 = min(item[1] for item in items)
                x1 = max(item[2] for item in items)
                y1 = max(item[3] for item in items)
                rendered.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1})

            for label in _RECIPIENT_BANK_LABELS:
                for index, row in enumerate(rendered):
                    if not _is_label_line(row["text"], label) and not row["text"].lower().startswith(label):
                        continue
                    # Same-line remainder to the right of the label text.
                    if row["text"].lower().startswith(label) and not _is_label_line(row["text"], label):
                        remainder = row["text"][len(label) :].lstrip(" \t:.—–-")
                        if remainder and not _looks_like_next_label(remainder):
                            return _norm_spaces(remainder), "explicit_pdf_field"

                    label_y_mid = (row["y0"] + row["y1"]) / 2.0
                    # Value to the right on the same visual line.
                    right_side = [
                        other
                        for other in rendered
                        if other is not row
                        and abs(((other["y0"] + other["y1"]) / 2.0) - label_y_mid) <= 4.0
                        and other["x0"] >= row["x1"] - 1.0
                        and (other["x0"] - row["x1"]) <= 220.0
                    ]
                    if right_side:
                        right_side.sort(key=lambda item: item["x0"])
                        value = _norm_spaces(" ".join(item["text"] for item in right_side))
                        if _is_usable_bank_value(value):
                            return value, "explicit_pdf_field"

                    # Otherwise first usable line below the label.
                    below = [
                        other
                        for other in rendered[index + 1 : index + 8]
                        if other["y0"] >= row["y0"] - 1.0
                    ]
                    for other in below:
                        if _is_usable_bank_value(other["text"]):
                            return other["text"], "explicit_pdf_field"
    finally:
        doc.close()
    return "", ""


def extract_recipient_bank_fields(
    pdf_bytes: bytes = b"",
    text: str = "",
    *,
    issuer_bank: str = "",
    sbp_route_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract recipient bank strictly from the labeled PDF field.

    Stateless: no module-level caches; every call depends only on arguments.
    """
    if not text and pdf_bytes and fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception:
            text = ""

    raw, source = _from_coordinates(pdf_bytes)
    if not _is_usable_bank_value(raw):
        raw, source = _from_plain_text(text)
    if not _is_usable_bank_value(raw):
        raw, source = "", ""

    normalized = _norm_spaces(raw)
    return {
        "issuer_bank": issuer_bank or "",
        "recipient_bank_raw": raw or "",
        "recipient_bank_normalized": normalized,
        "recipient_bank_source": source if normalized else "",
        "sbp_route_profile": dict(sbp_route_profile or {}),
        # Back-compat for older formatters.
        "receiver_bank": normalized or None,
    }


def attach_recipient_bank_fields(
    details: dict[str, Any] | None,
    pdf_bytes: bytes,
    text: str = "",
    *,
    issuer_bank: str = "",
    sbp_route_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge recipient-bank fields into an engine details dict (copy-safe)."""
    out = dict(details or {})
    fields = extract_recipient_bank_fields(
        pdf_bytes,
        text,
        issuer_bank=issuer_bank,
        sbp_route_profile=sbp_route_profile,
    )
    out["fields"] = {
        "issuer_bank": fields["issuer_bank"],
        "recipient_bank_raw": fields["recipient_bank_raw"],
        "recipient_bank_normalized": fields["recipient_bank_normalized"],
        "recipient_bank_source": fields["recipient_bank_source"],
    }
    out["issuer_bank"] = fields["issuer_bank"]
    out["recipient_bank_raw"] = fields["recipient_bank_raw"]
    out["recipient_bank_normalized"] = fields["recipient_bank_normalized"]
    out["recipient_bank_source"] = fields["recipient_bank_source"]
    out["sbp_route_profile"] = fields["sbp_route_profile"]
    return out
