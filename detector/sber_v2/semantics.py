"""Semantic field tuples + SBP linked tuple for Sber v2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..sber_profiles import (
    check_card_arithmetic,
    extract_legacy_document,
    extract_sbp_opid,
    parse_operation_datetime,
)
from ..sber_sbp_cipher import validate_legacy_document, validate_sber_sbp_cipher
from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from .atlas import known_sbp_markers, known_sbp_tail_prefixes
from .profile_gates import profile_allows_rule
from .types import SberFlag

_BAD_CONTROLS = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
}


@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "semantic") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_semantic_tuples(
    text: str,
    *,
    profile_id: str,
    dual_parser_missed: bool = False,
) -> CheckResult:
    out = CheckResult()
    try:
        controls = sorted({n for ch, n in _BAD_CONTROLS.items() if ch in (text or "")})
        if controls:
            out.flags.append(_f(
                "TEXT_LAYER_INCONSISTENT",
                f"невидимые управляющие символы ({', '.join(controls)})",
            ))
        if "\x00" in (text or "") or "\ufffd" in (text or "") or "൚" in (text or ""):
            out.flags.append(_f(
                "SBER_LINKED_SEMANTIC_TUPLE_CONFLICT",
                "битые символы / неверный знак рубля в текстовом слое",
            ))
        if "сейчас" in (text or "").lower():
            out.flags.append(_f(
                "SBER_LINKED_SEMANTIC_TUPLE_CONFLICT",
                "дата операции оставлена как «сейчас»",
            ))

        if profile_id == "card_other_ios":
            bad, detail = check_card_arithmetic(text)
            if bad:
                out.flags.append(_f(
                    "SBER_AMOUNT_ARITHMETIC_MISMATCH",
                    detail,
                ))
                out.flags.append(_f(
                    "SBER_LINKED_SEMANTIC_TUPLE_CONFLICT",
                    detail,
                ))

        # Required field missing only after dual-path miss AND exact profile gate
        if dual_parser_missed and profile_allows_rule(profile_id, require_exact=True):
            out.flags.append(_f(
                "SBER_REQUIRED_FIELD_MISSING",
                "критическое поле отсутствует в обоих парсерах",
            ))

        # SEQ phone-shell reassembly: gibberish FIO (alphabet ladder / consonant
        # runs) and landline-looking recipient DEF. Corpus: alpha-run ≤2,
        # consonant-run ≤3, recipient phone DEF always 9xx when present.
        field_flags = _check_fio_phone_artifacts(text or "")
        out.flags.extend(field_flags.flags)
        out.stats.update(field_flags.stats)

        nbsp_hits = find_trailing_nbsp_padding(text or "")
        if nbsp_hits:
            out.flags.append(_f(NBSP_CODE, padding_detail(nbsp_hits), group="fields"))

        # Jasper «Чек по операции» genuines never pad the date line with
        # leading/trailing ASCII spaces (corpus n=40: 0). SEQ shells emit
        # «    12 июня …» or «…(МСК)      ».
        header_date = re.search(r"Чек по операции\s*\n([^\n]+)", text or "")
        if header_date:
            line = header_date.group(1)
            out.stats["header_date_line"] = line.strip()[:60]
            lead = len(line) - len(line.lstrip(" "))
            trail = len(line) - len(line.rstrip(" "))
            if lead >= 2:
                out.flags.append(_f(
                    "SBER_HEADER_DATE_LEADING_WHITESPACE",
                    (
                        f"дата чека с leading ASCII-spaces ({lead} шт.): "
                        f"{line.strip()!r} — pad SEQ content-stream "
                        f"(в корпусе Jasper 0)"
                    ),
                    group="fields",
                ))
            elif trail >= 2:
                out.flags.append(_f(
                    "SBER_HEADER_DATE_TRAILING_WHITESPACE",
                    (
                        f"дата чека с trailing ASCII-spaces ({trail} шт.): "
                        f"{line.strip()!r} — pad SEQ content-stream "
                        f"(в корпусе Jasper 0)"
                    ),
                    group="fields",
                ))

        # Internal Jasper genuines never left-pad ФИО value lines with ASCII
        # spaces (corpus сбер 300×699 / 300×795: 0). SEQ content transplants
        # keep fixed-width field slots: «              Анна Иванова».
        for fio_m in re.finditer(
            r"(?m)^(ФИО получателя(?:\s+перевода)?|ФИО отправителя)\s*\n([^\n]+)",
            text or "",
        ):
            label, line = fio_m.group(1), fio_m.group(2)
            lead = len(line) - len(line.lstrip(" "))
            if lead < 2:
                continue
            out.stats["fio_leading_pad"] = {
                "label": label,
                "lead": lead,
                "sample": line.strip()[:40],
            }
            out.flags.append(_f(
                "SBER_FIO_LEADING_WHITESPACE",
                (
                    f"{label} с leading ASCII-spaces ({lead} шт.): "
                    f"{line.strip()!r} — fixed-width pad SEQ content-stream "
                    f"(в корпусе Jasper ФИО lead=0)"
                ),
                group="fields",
            ))
            break

        # SBP amount line never has a leading ASCII space before the digits
        # (corpus n=41: 0). SEQ pad emits « 1927.00  ₽».
        amount_line = re.search(r"Сумма перевода\s*\n([^\n]+)", text or "")
        if amount_line:
            line = amount_line.group(1)
            out.stats["amount_line"] = line.strip()[:40]
            lead = len(line) - len(line.lstrip(" "))
            if lead >= 1:
                out.flags.append(_f(
                    "SBER_AMOUNT_LEADING_WHITESPACE",
                    (
                        f"сумма с leading ASCII-space ({lead} шт.): "
                        f"{line!r} — pad SEQ content-stream "
                        f"(в корпусе SBP Jasper 0)"
                    ),
                    group="fields",
                ))

        # Bank name value never has trailing ASCII spaces (corpus n=41: 0).
        # SEQ fixed-width field pad: «ВТБ             ».
        bank_line = re.search(r"Банк получателя\s*\n([^\n]+)", text or "")
        if bank_line:
            line = bank_line.group(1)
            out.stats["bank_recipient_line"] = line.strip()[:40]
            trail = len(line) - len(line.rstrip(" "))
            if trail >= 1:
                out.flags.append(_f(
                    "SBER_BANK_NAME_TRAILING_WHITESPACE",
                    (
                        f"банк получателя с trailing ASCII-spaces "
                        f"({trail} шт.): {line!r} — pad SEQ content-stream "
                        f"(в корпусе SBP Jasper 0)"
                    ),
                    group="fields",
                ))

        sbp_fio = _SBP_RECV_FIO_RE.search(text or "")
        if sbp_fio:
            fio = sbp_fio.group(1).strip()
            out.stats["sbp_recipient_fio"] = fio
            if fio and not _SBP_RECV_FIO_OK.match(fio):
                out.flags.append(_f(
                    "SBER_SBP_RECIPIENT_FIO_FORMAT",
                    (
                        f"ФИО получателя перевода {fio!r} ≠ шаблон "
                        f"«Имя Отчество И» (корпус SBP-outgoing Jasper); "
                        f"SEQ payload/tm form"
                    ),
                    group="fields",
                ))

        if "Номер операции в СБП" in (text or ""):
            lines = (text or "").replace("\xa0", " ").splitlines()
            for index, line in enumerate(lines):
                if line.strip() != "ФИО отправителя" or index == 0:
                    continue
                sender = lines[index - 1].strip()
                if not sender or sender.lower().startswith(
                    ("перевод", "чек", "номер", "телефон", "банк")
                ):
                    continue
                out.stats["sbp_sender_fio"] = sender
                if not _SBP_SEND_FIO_OK.match(sender):
                    out.flags.append(_f(
                        "SBER_SBP_SENDER_FIO_FORMAT",
                        (
                            f"ФИО отправителя {sender!r} ≠ шаблон "
                            f"«Имя Отчество И.» (корпус SBP-outgoing Jasper)"
                        ),
                        group="fields",
                    ))
                break
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out


_CYRILLIC_VOWELS = frozenset("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
# Intrabank: +7 (9xx) xxx-xx-xx; SBP shells often omit parentheses: +7 9xx xxx-xx-xx
_PHONE_RE = re.compile(
    r"\+7\s*(?:\((\d{3})\)|(\d{3}))\s*\d{3}-\d{2}-\d{2}"
)
_FIO_FIELD_RE = re.compile(
    r"(?im)^(?:ФИО получателя(?:\s+перевода)?|ФИО отправителя)\s*\n\s*([^\n]+)"
)
# Exact SBP-outgoing Jasper genuines: «Имя Отчество И» (3 tokens, last = single
# Cyrillic letter). SEQ forms dump 2-token joke names («Катык Предсказуемович»).
_SBP_RECV_FIO_RE = re.compile(
    r"(?im)^ФИО получателя перевода\s*\n\s*([^\n]+)"
)
_SBP_RECV_FIO_OK = re.compile(
    r"^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ]$"
)
# Sender value sits on the line *before* «ФИО отправителя» and always ends
# with a single-letter initial + dot («… Т.»). SEQ dumps a full third word.
_SBP_SEND_FIO_OK = re.compile(
    r"^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ]\.$"
)
def _max_cyrillic_consonant_run(value: str) -> int:
    best = 0
    run = 0
    for char in value or "":
        is_cyrillic = ("А" <= char <= "я") or char in "Ёё"
        if is_cyrillic and char not in _CYRILLIC_VOWELS:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _max_cyrillic_alphabet_run(value: str) -> int:
    """Longest ascending codepoint run in lowercase Cyrillic letters."""
    best = 0
    run = 1
    prev: int | None = None
    for char in (value or "").lower():
        if not (("а" <= char <= "я") or char == "ё"):
            prev = None
            run = 1
            continue
        code = ord(char)
        if prev is not None and code == prev + 1:
            run += 1
            best = max(best, run)
        else:
            run = 1
        prev = code
    return best


def _check_fio_phone_artifacts(text: str) -> CheckResult:
    out = CheckResult()
    raw = text.replace("\xa0", " ").replace("\u202f", " ")

    phone = _PHONE_RE.search(raw)
    if phone:
        def_code = phone.group(1) or phone.group(2) or ""
        out.stats["recipient_phone_def"] = def_code
        if def_code and not def_code.startswith("9"):
            out.flags.append(_f(
                "SBER_PHONE_DEF_NOT_MOBILE",
                (
                    f"телефон получателя DEF={def_code} (не 9xx); "
                    f"в корпусе Сбер мобильный получатель всегда 9xx — "
                    f"синтетический номер SEQ-шаблона"
                ),
                group="fields",
            ))

    alpha_runs: list[int] = []
    cons_runs: list[int] = []
    seen_fio: set[str] = set()
    for match in _FIO_FIELD_RE.finditer(raw):
        fio = match.group(1).strip()
        if not fio or fio in seen_fio:
            continue
        # Skip non-name lines that sometimes land under FIO labels in
        # reordered SBP shells (operation type, bank name, etc.).
        if fio.lower().startswith(("перевод", "чек", "операция", "сбер", "банк")):
            continue
        seen_fio.add(fio)
        letters = sum(
            1 for ch in fio if ("А" <= ch <= "я") or ch in "Ёё"
        )
        alpha = _max_cyrillic_alphabet_run(fio)
        cons = _max_cyrillic_consonant_run(fio)
        alpha_runs.append(alpha)
        cons_runs.append(cons)
        # FIO consonant/alphabet-run HARDs removed — gibberish-name heuristics.

    if alpha_runs:
        out.stats["fio_alphabet_runs"] = alpha_runs
    if cons_runs:
        out.stats["fio_consonant_runs"] = cons_runs
    return out


def check_sbp_linked_tuple(text: str, *, profile_id: str) -> CheckResult:
    out = CheckResult()
    try:
        if profile_id not in ("sbp_outgoing", "sbp_request"):
            out.stats["skipped"] = "not_sbp_profile"
            return out

        opid = extract_sbp_opid(text)
        out.stats["sbp_opid"] = opid
        cipher = validate_sber_sbp_cipher(opid or "", text)
        out.stats["sbp_cipher"] = cipher.stats

        for cf in cipher.flags:
            if cf.code in (
                "SBER_SBP_ID_MISSING",
                "SBER_SBP_ID_STRUCTURE",
                "SBER_SBP_ID_TIMESTAMP",
            ):
                # Map timestamp/structure into linked-tuple HARD
                code = (
                    "SBER_SBP_TIMESTAMP_MISMATCH"
                    if "TIMESTAMP" in cf.code
                    else "SBER_SBP_LINKED_TUPLE_CONFLICT"
                )
                out.flags.append(_f(code, cf.detail, group="identifier"))
                out.flags.append(_f(
                    "SBER_SBP_LINKED_TUPLE_CONFLICT",
                    cf.detail,
                    group="identifier",
                ))

        # Corpus sbp_outgoing n=41: |Δt| ≤ 10s. SEQ 179579 = 12s.
        # Cipher already HARDs >90s; promote >10s as linked-tuple HARD.
        diff = cipher.stats.get("utc_diff_sec")
        if isinstance(diff, (int, float)) and abs(diff) > 10:
            if not any(f.code == "SBER_SBP_TIMESTAMP_MISMATCH" for f in out.flags):
                out.flags.append(_f(
                    "SBER_SBP_TIMESTAMP_MISMATCH",
                    f"|Δt|={abs(int(diff))}s > 10s между SBP core и операцией",
                    group="identifier",
                ))
                out.flags.append(_f(
                    "SBER_SBP_LINKED_TUPLE_CONFLICT",
                    f"SBP linked tuple timestamp |Δt|={abs(int(diff))}s",
                    group="identifier",
                ))

        if opid and re.match(r"^[AB][0-9A-Z]{31}$", opid):
            marker = opid[0]
            tail_p4 = opid[11:15]
            markers = known_sbp_markers()
            prefixes = known_sbp_tail_prefixes()
            if markers and marker not in markers:
                out.flags.append(_f(
                    "SBER_SBP_MARKER_UNKNOWN",
                    f"маркер SBP «{marker}» вне atlas",
                    tier="B",
                    group="B5_sbp_empirical",
                ))
            if prefixes and tail_p4 not in prefixes:
                out.flags.append(_f(
                    "SBER_SBP_EMPIRICAL_PROFILE",
                    f"хвост prefix4 «{tail_p4}» вне atlas (empirical)",
                    tier="B",
                    group="B5_sbp_empirical",
                ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out


def check_legacy_document(text: str, *, profile_id: str) -> CheckResult:
    out = CheckResult()
    if profile_id != "legacy_phone":
        return out
    try:
        doc = extract_legacy_document(text)
        out.stats["legacy_document"] = doc
        if not doc:
            out.flags.append(_f(
                "SBER_SBP_EMPIRICAL_PROFILE",
                "legacy document ID не найден",
                tier="DIAGNOSTIC",
            ))
            return out
        leg = validate_legacy_document(doc, text)
        out.stats["legacy_cipher"] = leg.stats
        for lf in leg.flags:
            out.flags.append(_f(
                "SBER_LINKED_SEMANTIC_TUPLE_CONFLICT",
                lf.detail,
                group="identifier",
            ))
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
