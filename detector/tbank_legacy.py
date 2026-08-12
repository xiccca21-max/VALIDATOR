"""
Т-Банк — полный forensic analyzer (JasperReports + OpenPDF).

Pipeline: structure → spec → forensics → font/glyf/FF2 → metadata → anti-edit → template.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

try:
    import fitz
except ImportError:
    fitz = None

from .anti_edit import run_checks as run_anti_edit_checks
from .corpus_signals import append_stats_only, emit_check
from .corpus_profiles import (
    CHANNEL_CARD,
    CHANNEL_PHONE,
    CHANNEL_SBP,
    PROFILE_VERSION,
    detect_receipt_channel,
    detect_receipt_subtype,
    receipt_subtype_label,
)
from .ff2_pool import ff2_to_log_dict, run_ff2_pool_check, _load_corpus, extract_ff2_fingerprints
from .font_layers import font_layers_to_log_dict, run_font_layer_checks
from .glyf_fingerprint import glyf_to_log_dict, run_glyf_checks
from .pdf_forensics import Weight, forensics_to_log_dict, run_pdf_forensics
from .sbp_cipher import extract_receipt_datetime, extract_sbp_opid
from .structure import (
    content_skeleton_hash,
    content_stream_bytes,
    find_streams,
    is_content_stream,
    validate_active_content,
    validate_incremental_updates,
    validate_pdf_structure,
    validate_stream_compression,
    xref_integrity,
)
from .tbank_invariants import channel_skeleton_pool, load as load_tbank_invariants
from .tbank_spec import run_tbank_spec_checks, spec_to_log_dict
from .tbank_corpus_spec import run_tbank_corpus_spec_checks, _page_dims
from .tbank_template_profile import run_tbank_template_checks
from .tbank_font_rebuilder import (
    rebuilder_to_log_dict,
    run_font_rebuilder_check,
)

VALIDATOR_VERSION = "0.6.3-v55"

_SIGNALS = {
    "forensic_high": 95,
    "forensic_medium": 50,
    "forensic_low": 15,
    "broken_xref": 95,
    "stream_reserialized": 95,
    "wrong_zlib_level": 85,
    "suspicious_producer": 95,
    "glyf_fingerprint": 95,
    "layered_profile_forgery": 95,
    "reassembly_forgery": 95,
    "font_render_forgery": 95,
    "content_stream_edit_trace": 95,
    "ruble_glyph_spacing": 95,
    "ff2_subset_unknown": 95,
    "template_profile": 95,
    "corpus_hard": 95,
    "corpus_soft": 15,
    "keywords_creation": 95,
    "creation_eq_operation": 95,
    "keywords_tail": 95,
    "id_hex_case": 95,
    "foreign_width": 95,
    "broken_glyphmap": 95,
    "phone_format": 95,
    "sbp_opid_structure": 95,
    "sbp_stream_field_order": 95,
    "content_skeleton_unknown": 95,
    "channel_skeleton_forgery": 95,
    "bfchar_in_tounicode": 95,
    "multiple_eof": 95,
    "prev_in_trailer": 95,
}

_BAD_PRODUCERS = [
    "pikepdf", "pypdf", "ilovepdf", "smallpdf", "reportlab", "pdfedit",
    "acrobat", "itext", "pdf-lib", "pdf_lib", "libreoffice", "canva",
]

_NATIVE_PRODUCERS = ("openpdf", "jasperreports", "jasper", "jaspersoft")

_AMOUNT_RE = re.compile(
    r"(?:сумма|итого|перевод)[^\d₽руб]{0,24}"
    r"([\d\s\u00a0\u202f]{3,}(?:[.,]\d{2})?)",
    re.IGNORECASE,
)

_KEYWORDS_RE = re.compile(rb"/Keywords\s*\(((?:[^()\\]|\\.)*)\)")
_CREATION_RE = re.compile(
    rb"/CreationDate\s*\(([^)]*)\)|/CreationDate\s*<([^>]*)>"
)
_MODDATE_RE = re.compile(
    rb"/ModDate\s*\(([^)]*)\)|/ModDate\s*<([^>]*)>"
)
_ID_RE = re.compile(rb"/ID\s*\[\s*<([^>]+)>\s*<([^>]+)>\s*\]")
_W_PRETTY_RE = re.compile(rb"/W\s*\[\s*\d+\s+\[")
_PHONE_FMT_RE = re.compile(r"^\+7 \(\d{3}\) \d{3}-\d{2}-\d{2}$")
_KW_DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})"
)
_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
)
_OP_LINE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})"
)
_BAD_TEXT_CONTROLS = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
    "\u2066": "bidi isolate",
    "\u2067": "bidi isolate",
    "\u2068": "bidi isolate",
    "\u2069": "bidi isolate",
}
_LATIN_HOMOGLYPHS = str.maketrans({
    "A": "А", "a": "а", "B": "В", "C": "С", "c": "с", "E": "Е",
    "e": "е", "H": "Н", "K": "К", "M": "М", "O": "О", "o": "о",
    "P": "Р", "p": "р", "T": "Т", "X": "Х", "x": "х", "Y": "У",
    "y": "у",
})
_CORE_RU_LABELS = frozenset({
    "Получатель", "Отправитель", "Комиссия", "Сумма", "Итого",
    "Телефон", "Карта", "Банк", "Статус", "Успешно", "Квитанция",
    "Перевод",
})
_COMPACT_AMOUNT_RE = re.compile(r"(?<!\d)\d{5,}₽")
_BAD_TEXT_CONTROLS = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
    "\u2066": "bidi isolate",
    "\u2067": "bidi isolate",
    "\u2068": "bidi isolate",
    "\u2069": "bidi isolate",
}
_LATIN_HOMOGLYPHS = str.maketrans({
    "A": "А", "a": "а",
    "B": "В",
    "C": "С", "c": "с",
    "E": "Е", "e": "е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О", "o": "о",
    "P": "Р", "p": "р",
    "T": "Т",
    "X": "Х", "x": "х",
    "Y": "У", "y": "у",
})
_CORE_RU_LABELS = frozenset({
    "Получатель",
    "Отправитель",
    "Комиссия",
    "Сумма",
    "Итого",
    "Телефон",
    "Карта",
    "Банк",
    "Статус",
    "Успешно",
    "Квитанция",
    "Перевод",
})

# Exact operator skeletons emitted by the local fake generator family. This is
# intentionally a blacklist of known-bad assemblies, not "unknown skeleton = fake".
_GENERATOR_SKELETONS = frozenset({
    "104eb3a947e4bc40",  # T-Bank intrabank/client clone
    "bc1d467eabb5bfae",  # T-Bank phone clone
    "220bf37ae2f7fa3c",  # card transfer clone (old run)
    "e4733e1c6cbe27b0",  # card transfer clone
    "8afaff6d932067fa",  # card number clone (old run)
    "293b41b126bde1bc",  # card number clone
})


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(p.get_text() for p in doc)
        doc.close()
        return text
    except Exception:
        return ""


def _pdf_metadata(pdf_bytes: bytes) -> tuple[str, str, str, str]:
    """Return (producer, creator, creationDate, modDate)."""
    if not fitz:
        return "", "", "", ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        meta = doc.metadata or {}
        doc.close()
        return (
            meta.get("producer") or "",
            meta.get("creator") or "",
            meta.get("creationDate") or "",
            meta.get("modDate") or "",
        )
    except Exception:
        return "", "", "", ""


def _meta_string(pdf_bytes: bytes, rx: re.Pattern[bytes]) -> str:
    m = rx.search(pdf_bytes)
    if not m:
        return ""
    raw = m.group(1) or (m.group(2) if m.lastindex and m.lastindex >= 2 else b"")
    if isinstance(raw, bytes):
        return raw.decode("latin1", "replace")
    return str(raw)


def _parse_kw_date(kw: str) -> datetime | None:
    m = _KW_DATE_RE.match((kw or "").strip())
    if not m:
        return None
    try:
        d, mo, y, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _parse_pdf_meta_date(value: str) -> datetime | None:
    m = _PDF_DATE_RE.match((value or "").strip())
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _operation_datetime(text: str) -> datetime | None:
    dt = extract_receipt_datetime(text, prefer_first_line=True)
    if dt:
        return dt.replace(tzinfo=None) if hasattr(dt, "tzinfo") else dt
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _OP_LINE_RE.match(line)
        if m:
            try:
                d, mo, y, h, mi, s = map(int, m.groups())
                return datetime(y, mo, d, h, mi, s)
            except ValueError:
                pass
        if line and not line[0].isdigit():
            break
    return None


def _sbp_opid(pdf_bytes: bytes) -> str | None:
    text = _pdf_text(pdf_bytes)
    return extract_sbp_opid(text)


def _is_sbp_receipt(pdf_bytes: bytes) -> bool:
    return detect_receipt_channel(_pdf_text(pdf_bytes)) == CHANNEL_SBP


def _sbp_opid_structure(pdf_bytes: bytes) -> tuple[bool, str]:
    try:
        if not _is_sbp_receipt(pdf_bytes):
            return (False, "")
        opid = _sbp_opid(pdf_bytes)
        text = _pdf_text(pdf_bytes)
        if not opid:
            return (True, "[SBP_CIPHER_MISSING] не найден идентификатор операции СБП")
        from .tbank_sbp_cipher import validate_tbank_sbp_cipher

        result = validate_tbank_sbp_cipher(opid, text)
        if result.flags:
            f = result.flags[0]
            return (True, f"[{f.code}] {f.detail}")
        return (False, "")
    except Exception:
        return (False, "")


def _id_hex_case(pdf_bytes: bytes) -> tuple[bool, str]:
    m = _ID_RE.search(pdf_bytes)
    if not m:
        return (False, "")
    ids = [g.decode("ascii", "replace") for g in m.groups()]
    upper = [i for i in ids if any(c in "ABCDEF" for c in i)]
    if upper:
        sample = upper[0][:32]
        return (
            True,
            f"идентификатор PDF (/ID) записан ЗАГЛАВНЫМИ hex-символами "
            f"(«{sample}…») — у OpenPDF Т-Банка всегда строчные",
        )
    return (False, "")


def _text_layer_semantic_forgeries(text: str) -> list[str]:
    """Hard text-layer contradictions, not profile drift."""
    flags: list[str] = []
    if not text:
        return flags

    controls = sorted({name for ch, name in _BAD_TEXT_CONTROLS.items() if ch in text})
    if controls:
        flags.append(
            "[TEXT_LAYER_INCONSISTENT] в видимом тексте есть невидимые управляющие "
            f"символы ({', '.join(controls)})"
        )

    for token in re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", text):
        normalized = token.translate(_LATIN_HOMOGLYPHS)
        if token != normalized and normalized in _CORE_RU_LABELS:
            flags.append(
                f"[BROKEN_CYRILLIC_MAPPING] служебное слово «{normalized}» "
                "набрано латинскими похожими буквами"
            )
            break

    compact = (text or "").replace("\u00a0", " ").replace("\u202f", " ")
    m = _COMPACT_AMOUNT_RE.search(compact)
    if m and re.search(r"(Сумма|Итого|Комиссия|Перевод)", compact, re.IGNORECASE):
        flags.append(
            f"[FIELD_FORMAT_INVALID] денежное значение записано не банковской "
            f"грамматикой: {m.group(0)}"
        )

    return flags


def _keywords_creation_mismatch(pdf_bytes: bytes) -> tuple[bool, str]:
    """
    У оригинала /Keywords = CreationDate и всегда ПОЗЖЕ времени перевода.
    Генератор часто ставит в Keywords время операции (≤ перевода).
    """
    kw = _meta_string(pdf_bytes, _KEYWORDS_RE)
    if not kw:
        return (False, "")
    kw_dt = _parse_kw_date(kw.split("|")[0].strip())
    if not kw_dt:
        return (False, "")
    op_dt = _operation_datetime(_pdf_text(pdf_bytes))
    if not op_dt:
        return (False, "")
    if (kw_dt - op_dt).total_seconds() > 3:
        return (False, "")
    return (
        True,
        f"дата в /Keywords ({kw_dt.strftime('%d.%m.%Y %H:%M:%S')}) "
        f"не позже перевода ({op_dt.strftime('%d.%m.%Y %H:%M:%S')}) — "
        f"у оригинала Keywords отражает момент формирования PDF",
    )


def _creation_eq_operation(pdf_bytes: bytes) -> tuple[bool, str]:
    cre = _meta_string(pdf_bytes, _CREATION_RE)
    if not cre:
        _, _, cre, _ = _pdf_metadata(pdf_bytes)
    cr_dt = _parse_pdf_meta_date(cre)
    op_dt = _operation_datetime(_pdf_text(pdf_bytes))
    if not cr_dt or not op_dt:
        return (False, "")
    delta = (cr_dt - op_dt).total_seconds()
    if delta > 3:
        return (False, "")
    return (
        True,
        f"CreationDate PDF ({cr_dt.strftime('%d.%m.%Y %H:%M:%S')}) "
        f"не позже перевода ({op_dt.strftime('%d.%m.%Y %H:%M:%S')}) — "
        f"у настоящего чека файл формируется после операции",
    )


def _keywords_tail_info(pdf_bytes: bytes) -> str:
    """Third /Keywords token is opaque backend data — never used for verdict."""
    kw = _meta_string(pdf_bytes, _KEYWORDS_RE)
    if not kw:
        return ""
    parts = [p.strip() for p in kw.split("|")]
    return parts[-1] if parts else ""


def _foreign_width_array(pdf_bytes: bytes) -> tuple[bool, str]:
    if _W_PRETTY_RE.search(pdf_bytes):
        return (
            True,
            "таблица /W записана с пробелами (pretty-print) — "
            "признак пересборки pikepdf/fontTools",
        )
    return (False, "")


def _bfchar_in_tounicode(pdf_bytes: bytes) -> tuple[bool, str]:
    for _raw, dec in find_streams(pdf_bytes):
        if is_content_stream(dec):
            continue
        if b"/CIDInit" in dec and b"beginbfchar" in dec.lower():
            return (
                True,
                "ToUnicode CMap содержит beginbfchar — в оригиналах "
                "Т-Банка используется только beginbfrange",
            )
    return (False, "")


def _channel_skeleton_forgery(pdf_bytes: bytes, text: str) -> tuple[bool, str]:
    """Hard when operator skeleton of the content stream is unknown for this channel."""
    pool = channel_skeleton_pool()
    if not pool or not text:
        return (False, "")
    channel = detect_receipt_channel(text)
    known = pool.get(channel)
    if not known:
        return (False, "")
    sk = content_skeleton_hash(pdf_bytes)
    if not sk or sk in known:
        return (False, "")
    return (
        True,
        f"канал «{channel}»: operator fingerprint {sk} не в корпусе "
        f"({len(known)} эталонных шаблонов)",
    )


def _known_generator_skeleton(pdf_bytes: bytes) -> tuple[bool, str]:
    sk = content_skeleton_hash(pdf_bytes)
    if not sk or sk not in _GENERATOR_SKELETONS:
        return (False, "")
    return (
        True,
        f"operator fingerprint {sk} совпадает с известной сборкой генератора",
    )


def _reassembly_forgery(pdf_bytes: bytes, text: str) -> tuple[bool, str]:
    """
    Hard when PDF assembly skeleton is unknown for the channel AND the F1/F2/F3
    FontFile2 triplet was never seen in the corpus.

    Safe for new genuine receipts that reuse a known Jasper assembly template
    (skeleton in pool) but get a new F1 subset for different names/amounts.
    Catches homebrew generators that steal bank fonts but assemble content streams
    differently from T-Bank's JasperReports output.
    """
    ch_sk_fake, ch_sk_detail = _channel_skeleton_forgery(pdf_bytes, text)
    if not ch_sk_fake:
        return (False, "")
    fps = extract_ff2_fingerprints(pdf_bytes)
    if not fps:
        return (False, "")
    triplets = {tuple(t) for t in _load_corpus().get("triplets", [])}
    if not triplets:
        return (False, "")
    trip = tuple(fps[layer]["sha256_16"] for layer in ("F1", "F2", "F3"))
    if trip in triplets:
        return (False, "")
    channel = detect_receipt_channel(text) if text else "phone"
    return (
        True,
        f"канал «{channel}»: чужая сборка PDF ({ch_sk_detail.split(':', 1)[-1].strip()}) "
        f"и новый набор FontFile2 {trip[0]}/{trip[1]}/{trip[2]}",
    )


def _sbp_stream_field_order_forgery(pdf_bytes: bytes, text: str) -> tuple[bool, str]:
    """
    Генераторы кладут «Счет списания» в content stream раньше «Идентификатор
    операции», хотя на странице блоки идут в обратном порядке (sort=True).
    Настоящий Jasper Т-Банка пишет поток в том же порядке, что и на экране.
  """
    if detect_receipt_channel(text) != CHANNEL_SBP:
        return (False, "")
    if "Счет списания" not in text or "Идентификатор операции" not in text:
        return (False, "")
    if not fitz:
        return (False, "")

    def _acct_before_id(sort: bool) -> bool | None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            raw = doc[0].get_text("text", sort=sort) if sort else doc[0].get_text()
            doc.close()
        except Exception:
            return None
        ai = raw.find("Счет списания")
        ii = raw.find("Идентификатор операции")
        if ai < 0 or ii < 0:
            return None
        return ai < ii

    stream_acct_first = _acct_before_id(False)
    visual_acct_first = _acct_before_id(True)
    if stream_acct_first is None or visual_acct_first is None:
        return (False, "")
    if stream_acct_first and not visual_acct_first:
        return (
            True,
            "в PDF-потоке «Счет списания» идёт раньше «Идентификатор операции», "
            "но на странице порядок обратный — типичная сборка генератора",
        )
    return (False, "")


def _content_skeleton_unknown(pdf_bytes: bytes) -> tuple[bool, str]:
    """Stats-oriented: skeleton hash absent from global corpus."""
    known = set(load_tbank_invariants().get("content_skeleton_hashes") or ())
    if not known:
        return (False, "")
    sk = content_skeleton_hash(pdf_bytes)
    if not sk or sk in known:
        return (False, "")
    return (
        True,
        f"скелет content stream {sk} не встречался в эталонных чеках Т-Банка "
        f"(известно {len(known)} шаблонов)",
    )


def _ruble_glyph_spacing(pdf_bytes: bytes) -> tuple[bool, str]:
    """
    Genuine Jasper/OpenPDF receipts render ALSRubl as a separate glyph: «3 990 i».
    Generator fakes often glue the ruble glyph to the amount: «56 000i».
    """
    text = _pdf_text(pdf_bytes)
    if not text:
        return (False, "")
    bad: list[str] = []
    for m in re.finditer(r"(?:Итого|Сумма)\n([^\n]+)", text):
        val = m.group(1).strip()
        if val.endswith("i") and not val.endswith(" i"):
            bad.append(val)
    if not bad:
        return (False, "")
    sample = bad[0][:40]
    return (
        True,
        f"символ рубля слит с суммой («{sample}») — в оригинале всегда "
        "пробел перед «i»",
    )


def _layered_profile_forgery(pdf_bytes: bytes, forensic) -> tuple[bool, str]:
    """
    Hard only when three independent signals align (LOOCV 0/128 on corpus):
    unknown channel skeleton + PROFILE_CLUSTER_OUTLIER + HIGH_RISK bucket.
    """
    pool = channel_skeleton_pool()
    if not pool or not fitz:
        return (False, "")
    text = _pdf_text(pdf_bytes)
    if not text:
        return (False, "")
    channel = detect_receipt_channel(text)
    known = pool.get(channel)
    if not known:
        return (False, "")
    sk = content_skeleton_hash(pdf_bytes)
    if not sk or sk in known:
        return (False, "")
    codes = {f.code for f in forensic.flags}
    if "PROFILE_CLUSTER_OUTLIER" not in codes:
        return (False, "")
    if forensic.checks.get("risk_bucket") != "HIGH_RISK":
        return (False, "")
    return (
        True,
        f"канал «{channel}»: скелет content stream {sk} не встречался в "
        f"эталонах ({len(known)} шаблонов) + статистический outlier",
    )


def _broken_glyphmap(pdf_bytes: bytes) -> tuple[bool, str]:
    text = _pdf_text(pdf_bytes)
    if not text:
        return (False, "")
    if "\ufffd" in text:
        return (True, "в текстовом слое символы замены U+FFFD — битая glyphmap")
    low = text.lower()
    if "(cid:" in low:
        return (True, "текст содержит необработанные CID-метки — повреждён glyphmap")
    bad = sum(1 for c in text if "\u0080" <= c <= "\u009f")
    if bad >= 3:
        return (
            True,
            f"битая кириллическая разметка ({bad} управляющих символов в тексте)",
        )
    return (False, "")


def _phone_format(pdf_bytes: bytes) -> tuple[bool, str]:
    text = _pdf_text(pdf_bytes)
    if detect_receipt_channel(text) != CHANNEL_PHONE:
        return (False, "")
    lines = [ln.strip() for ln in text.split("\n")]
    phone = None
    for i, ln in enumerate(lines):
        if ln == "Получатель" and i > 0:
            phone = lines[i - 1]
            break
        if "телефон получателя" in ln.lower() and i + 1 < len(lines):
            phone = lines[i + 1].strip()
            break
    if not phone:
        return (False, "")
    if _PHONE_FMT_RE.match(phone):
        return (False, "")
    return (
        True,
        f"номер телефона «{phone[:30]}» — у Т-Банка формат "
        "«+7 (XXX) XXX-XX-XX»",
    )


def _content_stream_edit_trace(pdf_bytes: bytes) -> tuple[bool, str]:
    """Detect manual padding artifacts in the decoded content stream."""
    content = content_stream_bytes(pdf_bytes)
    if not content:
        return (False, "")

    pad_comments = [
        ln for ln in content.split(b"\n")
        if ln.strip().startswith(b"%") and len(ln.strip()) > 12
    ]
    if pad_comments:
        return (
            True,
            f"padding-комментарии (%…) в content stream "
            f"({len(pad_comments)} строк) — след ручной правки",
        )

    et_pos = content.rfind(b"ET")
    if et_pos >= 0:
        after = content[et_pos + 2:]
        pad = len(after) - len(after.lstrip(b" \t\r\n\x0c"))
        if pad > 8:
            return (
                True,
                f"хвостовой padding {pad} байт после ET — "
                "признак редактирования content stream",
            )

    # Jasper/OpenPDF receipts end with the footer stroke block and one trailing
    # whitespace byte after PyMuPDF decodes the stream. Generator edits often
    # leave extra pad bytes without changing visible text.
    stripped = content.rstrip(b" \t\r\n\x0c")
    tail_pad = len(content) - len(stripped)
    if stripped.endswith(b"2 J") and tail_pad > 2:
        return (
            True,
            f"хвостовой padding {tail_pad} байт после footer-блока — "
            "content stream пересобран не как Jasper/OpenPDF",
        )
    return (False, "")


def _decoded_content_len(pdf_bytes: bytes) -> int:
    content = content_stream_bytes(pdf_bytes)
    return len(content) if content else 0


def _merge_forensics(
    flags: list, score: int, details: dict, forensic,
) -> tuple[list, int]:
    """Merge pdf_forensics result; skip duplicates already covered by legacy checks."""
    skip_prefixes = {
        "W_ARRAY_SERIALIZATION", "CMAP_BFRANGE", "TTF_HEAD",
        "TOUNICODE_PROFILE", "BFCHAR",
    }
    skip_codes = frozenset({"TTF_HMTX_COUNT_MISMATCH"})
    seen_codes: set[str] = set()
    for f in forensic.flags:
        if f.code in skip_codes:
            continue
        if any(f.code.startswith(p) for p in skip_prefixes):
            continue
        if f.code in seen_codes:
            continue
        seen_codes.add(f.code)
        delta = (
            _SIGNALS["forensic_high"] if f.weight == Weight.HIGH
            else _SIGNALS["forensic_medium"] if f.weight == Weight.MEDIUM
            else _SIGNALS["forensic_low"]
        )
        score += emit_check(details, flags, f"[{f.code}] {f.detail}", delta)
    details["forensics"] = forensics_to_log_dict(forensic)
    details["forensic_template"] = forensic.template
    details["forensic_risk_bucket"] = forensic.checks.get("risk_bucket")
    return flags, score


def _score_layer_flags(flags: list, score: int, layer_flags, default_high: int) -> tuple[list, int]:
    for lf in layer_flags:
        flags.append(f"[{lf.code}] {lf.detail}")
        w = getattr(lf, "weight", None)
        if w == Weight.HIGH:
            score += _SIGNALS["forensic_high"]
        elif w == Weight.MEDIUM:
            score += _SIGNALS["forensic_medium"]
        elif w == Weight.LOW:
            score += _SIGNALS["forensic_low"]
        else:
            score += default_high
    return flags, score


def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:
    if not file_hash:
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    flags: list[str] = []
    details: dict = {"file_hash": file_hash}
    score = 0

    text = _pdf_text(pdf_bytes)
    producer, creator, creation_date, mod_date = _pdf_metadata(pdf_bytes)
    channel = detect_receipt_channel(text) if text else CHANNEL_PHONE
    subtype = detect_receipt_subtype(text) if text else detect_receipt_subtype("")
    details["channel"] = channel
    details["receipt_subtype"] = subtype
    details["receipt_subtype_label"] = receipt_subtype_label(subtype)
    details["producer"] = producer
    details["creator"] = creator

    text_semantic_flags = _text_layer_semantic_forgeries(text)
    details["text_layer_semantic_forgeries"] = text_semantic_flags
    for flag in text_semantic_flags:
        flags.append(flag)
        score += _SIGNALS["forensic_high"]

    # ── 1. PDF shell (structure.py) ─────────────────────────────────────────
    s1 = validate_pdf_structure(pdf_bytes)
    for code, detail in zip(s1.codes, s1.details):
        flags.append(f"[{code}] {detail}")
        if "INVALID" in code or "MISMATCH" in code or "FAILED" in code:
            score += _SIGNALS["forensic_high"]
        else:
            score += _SIGNALS["forensic_medium"]
    details["structure_codes"] = s1.codes

    s2 = validate_incremental_updates(pdf_bytes)
    for code, detail in zip(s2.codes, s2.details):
        flags.append(f"[{code}] {detail}")
        if code in (
            "MULTIPLE_EOF_PRESENT", "MULTIPLE_XREF_PRESENT",
            "PREV_TRAILER_PRESENT", "INCREMENTAL_UPDATE_PRESENT",
        ):
            score += _SIGNALS["broken_xref"]
        else:
            score += _SIGNALS["forensic_medium"]
    details["incremental"] = s2.codes

    s_comp = validate_stream_compression(pdf_bytes)
    for code, detail in zip(s_comp.codes, s_comp.details):
        if "COMPRESSION" in code:
            flags.append(detail)
            score += _SIGNALS["wrong_zlib_level"]
        else:
            flags.append(f"[{code}] {detail}")
            score += _SIGNALS["forensic_low"]
    details["stream_compression"] = s_comp.codes

    s_act = validate_active_content(pdf_bytes)
    for code, detail in zip(s_act.codes, s_act.details):
        flags.append(f"[{code}] {detail}")
        if code in (
            "JAVASCRIPT_PRESENT", "ACTIVE_CONTENT_PRESENT",
            "OPENACTION_PRESENT", "DANGEROUS_ACTION_PRESENT",
            "EMBEDDED_FILE_PRESENT", "EMBEDDED_PAYLOAD_PRESENT",
            "ACROFORM_PRESENT", "XFA_PRESENT",
        ):
            score += _SIGNALS["forensic_high"]
        else:
            score += _SIGNALS["forensic_low"]
    details["active_content"] = s_act.codes

    xref_broken, xref_detail = xref_integrity(pdf_bytes)
    if xref_broken:
        flags.append(f"Целостность PDF нарушена: {xref_detail}")
        score += _SIGNALS["broken_xref"]

    # ── 2. Reserialized >> stream (skip native Jasper/OpenPDF) ──────────────
    reserialized = len(re.findall(rb">>[ \t\r\n]+stream", pdf_bytes))
    native = any(p in f"{producer} {creator}".lower() for p in _NATIVE_PRODUCERS)
    details["stream_reserialized_count"] = reserialized
    if reserialized > 0 and not native:
        flags.append(
            f"Потоки пересобраны сторонней библиотекой: {reserialized} шт."
        )
        score += _SIGNALS["stream_reserialized"]

    # ── 3. T-Bank spec (chadgpt-plus) ───────────────────────────────────────
    spec_res = run_tbank_spec_checks(pdf_bytes)
    details["tbank_spec"] = spec_to_log_dict(spec_res)
    if spec_res.stats.get("channel"):
        channel = spec_res.stats["channel"]
        details["channel"] = channel
    if spec_res.stats.get("subtype"):
        subtype = spec_res.stats["subtype"]
        details["receipt_subtype"] = subtype
        details["receipt_subtype_label"] = spec_res.stats.get("subtype_label")

    seen_codes: set[str] = set()
    for sf in spec_res.flags:
        if sf.code == "FOREIGN_PRODUCER":
            continue
        if sf.code == "AMOUNT_MISMATCH_BETWEEN_TOTAL_AND_DETAILS":
            continue
        if sf.code in seen_codes:
            continue
        seen_codes.add(sf.code)
        flags.append(f"[{sf.code}] {sf.detail}")
        score += _SIGNALS["forensic_high"]

    combined = f"{producer} {creator}".lower()
    for bp in _BAD_PRODUCERS:
        if bp in combined:
            flags.append(f"[FOREIGN_PRODUCER] сторонний инструмент PDF: «{bp}»")
            score += _SIGNALS["suspicious_producer"]
            break

    # ── 4. Deep forensics ───────────────────────────────────────────────────
    forensic = run_pdf_forensics(pdf_bytes, bank="tbank", channel=channel)
    flags, score = _merge_forensics(flags, score, details, forensic)

    lp_fake, lp_detail = _layered_profile_forgery(pdf_bytes, forensic)
    details["layered_profile_forgery"] = lp_fake
    if lp_fake:
        score += emit_check(
            details, flags,
            f"[TBANK_LAYERED_PROFILE_FORGERY] {lp_detail}",
            _SIGNALS["layered_profile_forgery"],
        )

    # ── 5. Font layers & amounts ────────────────────────────────────────────
    fl_res = run_font_layer_checks(pdf_bytes, bank="tbank")
    details["font_layers"] = font_layers_to_log_dict(fl_res)
    flags, score = _score_layer_flags(flags, score, fl_res.flags, _SIGNALS["forensic_high"])

    glyf_res = run_glyf_checks(pdf_bytes)
    details["glyf"] = glyf_to_log_dict(glyf_res)
    for gf in glyf_res.flags:
        score += emit_check(
            details, flags, f"[{gf.code}] {gf.detail}", _SIGNALS["glyf_fingerprint"],
        )

    ff2_res = run_ff2_pool_check(pdf_bytes)
    details["ff2_pool"] = ff2_to_log_dict(ff2_res)
    for ff in ff2_res.flags:
        score += emit_check(
            details, flags, f"[{ff.code}] {ff.detail}", _SIGNALS["ff2_subset_unknown"],
        )

    ff2_stats = ff2_res.stats or {}
    details["ff2_triplet_known"] = bool(ff2_stats.get("ff2_triplet_known"))
    details["ff2_unknown_layers"] = ff2_stats.get("ff2_unknown_layers") or []

    # ── 6. T-Bank metadata & logic ──────────────────────────────────────────
    ch_sk_fake, ch_sk_detail = _channel_skeleton_forgery(pdf_bytes, text)
    details["channel_skeleton_forgery"] = ch_sk_fake
    details["channel_skeleton"] = content_skeleton_hash(pdf_bytes)
    if ch_sk_fake:
        details.setdefault("stats_only", []).append(
            f"[TBANK_CHANNEL_SKELETON_UNKNOWN] {ch_sk_detail}"
        )

    reasm_fake, reasm_detail = _reassembly_forgery(pdf_bytes, text)
    details["reassembly_forgery"] = reasm_fake
    if reasm_fake:
        details.setdefault("stats_only", []).append(
            f"[TBANK_REASSEMBLY_FORGERY] {reasm_detail}"
        )

    gen_sk_fake, gen_sk_detail = _known_generator_skeleton(pdf_bytes)
    details["known_generator_skeleton"] = gen_sk_fake
    if gen_sk_fake:
        flags.append(f"[TBANK_KNOWN_GENERATOR_SKELETON] {gen_sk_detail}")
        score += _SIGNALS["forensic_high"]

    sbp_ord_fake, sbp_ord_detail = _sbp_stream_field_order_forgery(pdf_bytes, text)
    details["sbp_stream_field_order"] = sbp_ord_fake
    if sbp_ord_fake and ch_sk_fake:
        flags.append(f"[TBANK_SBP_STREAM_FIELD_ORDER] {sbp_ord_detail}")
        score += _SIGNALS["sbp_stream_field_order"]

    rb_res = run_font_rebuilder_check(pdf_bytes)
    details["font_rebuilder"] = rebuilder_to_log_dict(rb_res)
    if rb_res.is_fake:
        for rf in rb_res.flags:
            flags.append(f"[{rf.code}] {rf.detail}")
            score += _SIGNALS["forensic_high"]

    # SHA логируем в details для аналитики
    details["content_stream_sha"] = (
        hashlib.sha256(content_stream_bytes(pdf_bytes) or b"").hexdigest()[:16]
        if content_stream_bytes(pdf_bytes)
        else ""
    )

    sk_fake, sk_detail = _content_skeleton_unknown(pdf_bytes)
    details["content_skeleton_unknown"] = sk_fake
    details["content_skeleton"] = content_skeleton_hash(pdf_bytes)
    if sk_fake:
        details.setdefault("stats_only", []).append(
            f"[TBANK_CONTENT_SKELETON_UNKNOWN] {sk_detail}"
        )

    rb_fake, rb_detail = _ruble_glyph_spacing(pdf_bytes)
    details["ruble_glyph_spacing"] = rb_fake
    if rb_fake:
        flags.append(f"[TBANK_RUBLE_GLYPH_SPACING] {rb_detail}")
        score += _SIGNALS["ruble_glyph_spacing"]

    ce_fake, ce_detail = _creation_eq_operation(pdf_bytes)
    details["creation_eq_operation"] = ce_fake
    if ce_fake:
        flags.append(f"[creation_eq_operation] {ce_detail}")
        score += _SIGNALS["creation_eq_operation"]

    kc_fake, kc_detail = _keywords_creation_mismatch(pdf_bytes)
    details["keywords_creation_mismatch"] = kc_fake
    if kc_fake:
        flags.append(f"[keywords_creation] {kc_detail}")
        score += _SIGNALS["keywords_creation"]

    kt_tail = _keywords_tail_info(pdf_bytes)
    details["keywords_tail_token"] = kt_tail
    if kt_tail:
        details.setdefault("stats_only", []).append(
            f"[KEYWORDS_THIRD_TOKEN_OPAQUE] третий токен /Keywords={kt_tail} (не влияет на verdict)"
        )

    ih_fake, ih_detail = _id_hex_case(pdf_bytes)
    details["id_hex_case"] = ih_fake
    if ih_fake:
        flags.append(f"[id_hex_case] {ih_detail}")
        score += _SIGNALS["id_hex_case"]

    fw_fake, fw_detail = _foreign_width_array(pdf_bytes)
    details["foreign_width_array"] = fw_fake
    if fw_fake:
        flags.append(f"[foreign_width_array] {fw_detail}")
        score += _SIGNALS["foreign_width"]

    bc_fake, bc_detail = _bfchar_in_tounicode(pdf_bytes)
    details["bfchar_in_tounicode"] = bc_fake
    if bc_fake:
        details.setdefault("stats_only", []).append(
            f"[BFCHAR_IN_TOUNICODE] {bc_detail}"
        )

    bg_fake, bg_detail = _broken_glyphmap(pdf_bytes)
    details["broken_glyphmap"] = bg_fake
    if bg_fake:
        flags.append(f"[broken_glyphmap] {bg_detail}")
        score += _SIGNALS["broken_glyphmap"]

    if channel == CHANNEL_PHONE:
        pf_fake, pf_detail = _phone_format(pdf_bytes)
        details["phone_format"] = pf_fake
        if pf_fake:
            flags.append(f"[phone_format] {pf_detail}")
            score += _SIGNALS["phone_format"]

    if channel == CHANNEL_SBP:
        sf_fake, sf_detail = _sbp_opid_structure(pdf_bytes)
        details["sbp_opid_structure"] = sf_fake
        details["sbp_opid"] = _sbp_opid(pdf_bytes)
        if sf_fake:
            flags.append(sf_detail if sf_detail.startswith("[") else f"[sbp_opid_structure] {sf_detail}")
            score += _SIGNALS["sbp_opid_structure"]

    # ── 7. Content stream edit trace ────────────────────────────────────────
    cs_fake, cs_detail = _content_stream_edit_trace(pdf_bytes)
    details["content_stream_edit_trace"] = cs_fake
    if cs_fake:
        flags.append(f"[TBANK_CONTENT_STREAM_EDIT] {cs_detail}")
        score += _SIGNALS["content_stream_edit_trace"]

    # ── 8. Anti-edit (reuse, ModDate drift, empty text layer) ───────────────
    ae_res = run_anti_edit_checks(
        pdf_bytes,
        bank_key="tbank",
        text=text,
        content_decoded=_decoded_content_len(pdf_bytes),
        creation_date=creation_date,
        mod_date=mod_date,
        file_hash_value=file_hash,
    )
    details["anti_edit"] = ae_res.stats
    for af in ae_res.flags:
        flags.append(f"[{af.code}] {af.detail}")
        score += _SIGNALS["forensic_high"]

    # ── 9. Template profile (height → BT/Tj, label coords) ──────────────────
    tpl_res = run_tbank_template_checks(pdf_bytes)
    details["template_profile"] = tpl_res.stats
    for tf in tpl_res.flags:
        score += emit_check(
            details, flags, f"[{tf.code}] {tf.detail}", _SIGNALS["template_profile"],
        )

    # ── 10. Corpus spec (shell, F3, operators, coords, baseline) ───────────
    cs_res = run_tbank_corpus_spec_checks(
        pdf_bytes,
        text=text,
        meta={"producer": producer, "creator": creator},
    )
    details["corpus_spec"] = cs_res.stats
    details["receipt_family"] = cs_res.family
    details["category_scores"] = cs_res.category_scores
    for cf in cs_res.flags:
        line = f"[{cf.code}] {cf.detail}"
        if cf.hard:
            score += emit_check(details, flags, line, _SIGNALS["corpus_hard"])
        else:
            score += emit_check(details, flags, line, cf.soft_weight or _SIGNALS["corpus_soft"])

    details["validator_version"] = VALIDATOR_VERSION
    details["profile_version"] = PROFILE_VERSION

    from .verdict import finalize_verdict

    verdict, emoji, effective_score, forgery_flags = finalize_verdict(score, flags)
    details["user_message"] = (
        "Обнаружена подделка." if verdict == "ФЕЙК"
        else "Признаков подделки не найдено."
    )

    return {
        "verdict": verdict,
        "emoji": emoji,
        "score": effective_score,
        "flags": forgery_flags,
        "details": details,
    }
