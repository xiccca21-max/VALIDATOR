"""Alfa v2 receipt profile and semantic checks.

This module is deliberately independent from the v2 verdict pipeline.  It
returns evidence-rich dataclasses so the pipeline can decide how tiers affect
the final verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

METHOD_SBP = "sbp"
METHOD_CARD = "card"
METHOD_PHONE = "phone"
METHOD_UNKNOWN = "unknown"

EMITTER_ORACLE = "oracle_bi"
EMITTER_QUARTZ = "quartz_ios"
EMITTER_UNKNOWN = "unknown"

_OPERATION_ID_RE = re.compile(r"(?<![A-Z0-9])([A-Z]\d{15})(?![A-Z0-9])")
_DATE_RE = re.compile(
    r"(\d{2})[.](\d{2})[.](\d{4})(?:\s*(?:г[.]?)?)"
    r"(?:\s+|,\s*)(\d{2}):(\d{2})(?::(\d{2}))?"
)
_SBP_ID_RE = re.compile(r"(?<![A-Z0-9])([AB][0-9A-Z]{31})(?![A-Z0-9])")
_MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0\u202f]\d{3})*|\d+)"
    r"(?:[,.](\d{1,2}))?\s*(?:RUR|RUB|₽|руб(?:[.]|ля|лей)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticFlag:
    code: str
    detail: str
    tier: str = "HARD"
    group: str = "semantic"


@dataclass
class SemanticResult:
    flags: list[SemanticFlag] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def add(
        self,
        code: str,
        detail: str,
        tier: str = "HARD",
        group: str = "semantic",
    ) -> None:
        self.flags.append(SemanticFlag(code, detail, tier, group))


@dataclass(frozen=True)
class EmitterEvidence:
    """Normalized PDF evidence supplied by the caller.

    ``object_graph`` and ``resources`` may be mappings, token sequences, or
    descriptive strings.  Explicit ``*_hint`` values are useful when the PDF
    parser already classified a layer.
    """

    producer: str = ""
    pdf_version: str = ""
    object_count: int | None = None
    object_graph: object = None
    resources: object = None
    icc_profile: object = None
    object_graph_hint: str = ""
    resources_hint: str = ""
    icc_hint: str = ""


@dataclass(frozen=True)
class AmountFields:
    amount: Decimal | None = None
    fee: Decimal | None = None
    debit: Decimal | None = None
    total: Decimal | None = None
    raw: Mapping[str, str] = field(default_factory=dict)


def _norm(text: str) -> str:
    return " ".join(
        (text or "")
        .replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("ё", "е")
        .lower()
        .split()
    )


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").upper())


def _method_evidence(text: str) -> dict[str, list[str]]:
    low = _norm(text)
    compact = _compact(text)
    evidence: dict[str, list[str]] = {
        METHOD_SBP: [],
        METHOD_CARD: [],
        METHOD_PHONE: [],
    }

    if "квитанция о переводе по сбп" in low:
        evidence[METHOD_SBP].append("title")
    if "идентификатор операции в сбп" in low or _SBP_ID_RE.search(compact):
        evidence[METHOD_SBP].append("sbp_id")

    if (
        "квитанция о переводе с карты на карту" in low
        or "номер карты отправителя" in low
        or "номер карты получателя" in low
    ):
        evidence[METHOD_CARD].append("card_fields")

    # Recipient phone is common on SBP receipts — not phone-method evidence.
    # Intrabank title is the deterministic phone/internal marker.
    if "квитанция о переводе клиенту альфа-банка" in low:
        evidence[METHOD_PHONE].append("title")
    return evidence


def classify_submethod(text: str) -> str:
    """Classify SBP/card/phone before applying any field contract."""
    evidence = _method_evidence(text)
    present = [method for method, markers in evidence.items() if markers]
    if len(present) == 1:
        return present[0]
    if len(present) > 1:
        # Titles are the strongest visible method declaration.
        for method in (METHOD_SBP, METHOD_CARD, METHOD_PHONE):
            if "title" in evidence[method]:
                return method
        return present[0]
    return METHOD_UNKNOWN


classify_method = classify_submethod


def _blob(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{k} {v}" for k, v in value.items()).lower()
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(map(str, value)).lower()
    return str(value).lower()


def _hint(value: str) -> str:
    low = (value or "").lower()
    if "oracle" in low:
        return EMITTER_ORACLE
    if "quartz" in low or "ios" in low:
        return EMITTER_QUARTZ
    return EMITTER_UNKNOWN


def _emitter_layers(evidence: EmitterEvidence) -> dict[str, str]:
    layers: dict[str, str] = {}
    producer = evidence.producer.lower()
    if "oracle bi publisher" in producer:
        layers["producer"] = EMITTER_ORACLE
    elif "quartz pdfcontext" in producer and "ios" in producer:
        layers["producer"] = EMITTER_QUARTZ

    version = evidence.pdf_version.strip().removeprefix("%PDF-")
    if version == "1.6":
        layers["pdf_version"] = EMITTER_ORACLE
    elif version == "1.3":
        layers["pdf_version"] = EMITTER_QUARTZ

    graph_hint = _hint(evidence.object_graph_hint)
    graph_blob = _blob(evidence.object_graph)
    if graph_hint != EMITTER_UNKNOWN:
        layers["object_graph"] = graph_hint
    elif evidence.object_count == 16 or any(
        token in graph_blob for token in ("oracle bi", "im0 do", "im1 do")
    ):
        layers["object_graph"] = EMITTER_ORACLE
    elif any(token in graph_blob for token in ("quartz", "cgpdf", "ios")):
        layers["object_graph"] = EMITTER_QUARTZ

    resource_hint = _hint(evidence.resources_hint)
    resources = _blob(evidence.resources)
    if resource_hint != EMITTER_UNKNOWN:
        layers["resources"] = resource_hint
    elif "tahoma" in resources or all(x in resources for x in ("900", "105", "603", "258")):
        layers["resources"] = EMITTER_ORACLE
    elif "font000000" in resources or "aaaaab+" in resources:
        layers["resources"] = EMITTER_QUARTZ

    icc_hint = _hint(evidence.icc_hint)
    icc = _blob(evidence.icc_profile)
    if icc_hint != EMITTER_UNKNOWN:
        layers["icc"] = icc_hint
    elif "oracle" in icc:
        layers["icc"] = EMITTER_ORACLE
    elif any(token in icc for token in ("apple", "display p3", "quartz", "ios")):
        layers["icc"] = EMITTER_QUARTZ
    return layers


def classify_emitter(evidence: EmitterEvidence | None = None, **kwargs: object) -> SemanticResult:
    """Classify Oracle BI vs Quartz iOS from independent PDF layers.

    Producer is evidence but never emits a flag by itself.  A cross-layer
    conflict requires contradictory emitter claims from at least two distinct
    layers.
    """
    if evidence is None:
        evidence = EmitterEvidence(**kwargs)
    layers = _emitter_layers(evidence)
    result = SemanticResult(stats={"emitter_layers": layers})
    oracle_layers = [name for name, value in layers.items() if value == EMITTER_ORACLE]
    quartz_layers = [name for name, value in layers.items() if value == EMITTER_QUARTZ]

    if oracle_layers and quartz_layers:
        result.stats["emitter"] = EMITTER_UNKNOWN
        result.add(
            "ALFA_PROFILE_CROSS_LAYER_CONFLICT",
            "PDF layers contradict each other: "
            f"Oracle={','.join(oracle_layers)}; Quartz={','.join(quartz_layers)}",
            group="profile",
        )
    elif len(oracle_layers) >= 2:
        result.stats["emitter"] = EMITTER_ORACLE
    elif len(quartz_layers) >= 2:
        result.stats["emitter"] = EMITTER_QUARTZ
    else:
        result.stats["emitter"] = EMITTER_UNKNOWN
        result.stats["producer_only"] = set(layers) == {"producer"}
    return result


def _has(text: str, *labels: str) -> bool:
    low = _norm(text)
    return any(_norm(label) in low for label in labels)


def _card_is_interbank(text: str) -> bool:
    low = _norm(text)
    return any(
        marker in low
        for marker in (
            "банк получателя",
            "код авторизации",
            "код терминала",
            "номер терминала",
        )
    )


def validate_field_contract(text: str, method: str | None = None) -> SemanticResult:
    """Validate method-specific field presence after method classification."""
    method = method or classify_submethod(text)
    evidence = _method_evidence(text)
    result = SemanticResult(
        stats={
            "method": method,
            "method_evidence": evidence,
            "corpus_contract_counts": {"sbp": 37, "card": 2, "phone": 1},
        }
    )
    proven = [name for name, markers in evidence.items() if markers]
    if len(proven) > 1:
        result.add(
            "ALFA_FIELD_SET_METHOD_CONFLICT",
            "proven field families are mixed: "
            + ", ".join(f"{name}({','.join(evidence[name])})" for name in proven),
            group="fields",
        )
        return result

    common = {
        "amount": ("сумма перевода",),
        "fee": ("комиссия",),
        "operation_date": ("дата и время перевода",),
        "operation_id": ("номер операции",),
    }
    required: dict[str, tuple[str, ...]] = dict(common)
    forbidden: dict[str, tuple[str, ...]] = {}

    if method == METHOD_SBP:
        required.update(
            {
                "recipient": ("получатель",),
                "recipient_phone": ("телефон получателя", "номер телефона получателя"),
                "recipient_bank": ("банк получателя",),
                "sbp_id": ("идентификатор операции в сбп",),
            }
        )
        amounts = parse_amounts(text)
        if amounts.fee is not None and amounts.fee > 0:
            required["commission_debit"] = (
                "списано с учетом комиссии",
                "списано с учётом комиссии",
            )
    elif method == METHOD_CARD:
        required.update(
            {
                "sender_card": ("номер карты отправителя",),
                "recipient_card": ("номер карты получателя",),
            }
        )
        if _card_is_interbank(text):
            required.update(
                {
                    "authorization": ("код авторизации",),
                    "terminal": ("код терминала", "номер терминала"),
                }
            )
    elif method == METHOD_PHONE:
        required.update(
            {
                "recipient": ("получатель",),
                "recipient_phone": ("телефон получателя", "номер телефона получателя"),
            }
        )
        forbidden = {
            "recipient_bank": ("банк получателя", "банк отправителя"),
            "sbp_id": ("идентификатор операции в сбп",),
        }

    missing = [name for name, aliases in required.items() if not _has(text, *aliases)]
    unexpected = [name for name, aliases in forbidden.items() if _has(text, *aliases)]
    result.stats["required_fields"] = sorted(required)
    result.stats["missing_fields"] = missing
    result.stats["unexpected_fields"] = unexpected
    if missing or unexpected:
        detail_parts = []
        if missing:
            detail_parts.append("missing " + ", ".join(missing))
        if unexpected:
            detail_parts.append("forbidden " + ", ".join(unexpected))
        result.add(
            "ALFA_FIELD_CONTRACT_MISMATCH",
            "; ".join(detail_parts),
            tier="B",
            group="B5_content_layout",
        )
    return result


validate_contract = validate_field_contract


def extract_operation_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    low = raw.lower()
    for label in ("дата и время перевода", "дата и время операции", "дата операции"):
        start = low.find(label)
        if start >= 0:
            match = _DATE_RE.search(raw[start : start + 120])
            if match:
                break
    else:
        match = _DATE_RE.search(raw)
    if not match:
        return None
    day, month, year, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0)
        )
    except ValueError:
        return None


def extract_operation_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_OPERATION_ID_RE.findall((text or "").upper())))


def validate_operation_ids(text: str, method: str | None = None) -> SemanticResult:
    method = method or classify_submethod(text)
    operation_ids = extract_operation_ids(text)
    result = SemanticResult(stats={"method": method, "operation_ids": operation_ids})

    if not operation_ids:
        result.add(
            "ALFA_OPERATION_ID_STRUCTURE",
            "no exact 16-character operation ID found",
            group="operation_id",
        )
        return result

    dt = extract_operation_datetime(text)
    if dt:
        result.stats["operation_datetime"] = dt.isoformat(sep=" ")
    for operation_id in operation_ids:
        if len(operation_id) != 16 or not re.fullmatch(r"[A-Z]\d{15}", operation_id):
            result.add(
                "ALFA_OPERATION_NUMBER_FORMAT",
                f"operation ID {operation_id!r} is not exactly 16 characters",
                group="operation_id",
            )
            continue
        # No C16/C42/C07/Z09 family pins — bank mint codes vary; FP risk.
        if dt and operation_id[3:9] != dt.strftime("%d%m%y"):
            result.add(
                "ALFA_OPERATION_DATE_LINK_MISMATCH",
                f"{operation_id}[3:9]={operation_id[3:9]} but visible operation "
                f"date is {dt.strftime('%d%m%y')}",
                group="operation_id",
            )
        # Known generator signature: literal embed of visible datetime after C16.
        # Absent from the Alfa original corpus; decisive KNOWN on its own.
        if dt and len(operation_id) == 16:
            synth = "C16" + dt.strftime("%d%m%y") + dt.strftime("%H%M%S")
            if operation_id.startswith(synth):
                result.stats["synthetic_operation_number_time_embedding"] = operation_id
                result.add(
                    "ALFA_KNOWN_GENERATOR_OPERATION_TIME_EMBEDDING",
                    f"{operation_id} embeds visible datetime "
                    f"{dt.strftime('%d.%m.%Y %H:%M:%S')} as C16+DDMMYY+HHMMSS+digit",
                    tier="KNOWN",
                    group="operation_id",
                )
    return result


validate_operation_id = validate_operation_ids


def _next_value(lines: Sequence[str], index: int) -> str:
    inline = lines[index].split(":", 1)
    if len(inline) == 2 and inline[1].strip():
        return inline[1].strip()
    for value in lines[index + 1 : index + 5]:
        if value.strip():
            return value.strip()
    return ""


def validate_field_value_binding(
    text: str,
    method: str | None = None,
) -> SemanticResult:
    """Ensure SBP labels are followed by values of the expected type.

    Oracle BI extracts each left-column label immediately before its value.
    Checking global field presence alone misses clone/template shifts where a
    date is painted under the debit label and every following value moves down
    one semantic row.  Require two contradictions so a single extraction quirk
    cannot decide the verdict.
    """
    method = method or classify_submethod(text)
    result = SemanticResult()
    if method != METHOD_SBP:
        return result

    lines = [
        line.strip()
        for line in (text or "").replace("\u202f", " ").replace("\xa0", " ").splitlines()
        if line.strip()
    ]
    checks = (
        (
            ("списано с учетом комиссии", "списано с учётом комиссии"),
            "денежная сумма",
            lambda value: _money(value) is not None,
        ),
        (
            ("дата и время перевода",),
            "дата и время",
            lambda value: _DATE_RE.search(value) is not None,
        ),
        (
            ("номер операции",),
            "16-символьный номер операции",
            lambda value: _OPERATION_ID_RE.search(value.upper()) is not None,
        ),
    )
    mismatches: list[dict[str, str]] = []
    observations: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        normalized = _norm(line)
        for labels, expected, predicate in checks:
            if not any(normalized.startswith(_norm(label)) for label in labels):
                continue
            value = _next_value(lines, index)
            valid = bool(value and predicate(value))
            observation = {
                "label": line,
                "value": value,
                "expected": expected,
                "valid": valid,
            }
            observations.append(observation)
            if not valid:
                mismatches.append({
                    "label": line,
                    "value": value,
                    "expected": expected,
                })
            break

    result.stats["field_value_bindings"] = observations
    result.stats["field_value_binding_mismatch_count"] = len(mismatches)
    if len(mismatches) >= 2:
        detail = "; ".join(
            f"{item['label']!r} → {item['value']!r}, ожидалось: {item['expected']}"
            for item in mismatches
        )
        result.add(
            "ALFA_FIELD_VALUE_BINDING_CONFLICT",
            "значения сдвинуты относительно подписей полей: " + detail,
            group="fields",
        )
    return result


def _money(value: str) -> Decimal | None:
    match = _MONEY_RE.search(value or "")
    if not match:
        return None
    integer, fraction = match.groups()
    normalized = re.sub(r"[ \u00a0\u202f]", "", integer)
    normalized += "." + (fraction or "0").ljust(2, "0")
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_amounts(text: str) -> AmountFields:
    lines = [
        line.strip()
        for line in (text or "").replace("\u202f", " ").replace("\xa0", " ").splitlines()
    ]
    labels: tuple[tuple[str, str], ...] = (
        ("debit", "списано с учетом комиссии"),
        ("debit", "списано с учётом комиссии"),
        ("total", "итого"),
        ("amount", "сумма перевода"),
        ("fee", "комиссия"),
    )
    values: dict[str, Decimal] = {}
    raw_values: dict[str, str] = {}
    for index, line in enumerate(lines):
        low = _norm(line)
        for key, label in labels:
            if key not in values and low.startswith(_norm(label)):
                raw = _next_value(lines, index)
                value = _money(raw)
                if value is not None:
                    values[key] = value
                    raw_values[key] = raw
                break
    return AmountFields(
        amount=values.get("amount"),
        fee=values.get("fee"),
        debit=values.get("debit"),
        total=values.get("total"),
        raw=raw_values,
    )


def validate_amount_arithmetic(text: str) -> SemanticResult:
    amounts = parse_amounts(text)
    result = SemanticResult(
        stats={
            "amounts": {
                key: str(value)
                for key, value in (
                    ("amount", amounts.amount),
                    ("fee", amounts.fee),
                    ("debit", amounts.debit),
                    ("total", amounts.total),
                )
                if value is not None
            }
        }
    )
    if amounts.amount is None or amounts.fee is None:
        return result
    expected = amounts.amount + amounts.fee
    observed = [
        (label, value)
        for label, value in (("debit", amounts.debit), ("total", amounts.total))
        if value is not None
    ]
    mismatches = [
        f"{label}={value} (expected {expected})"
        for label, value in observed
        if value != expected
    ]
    if mismatches:
        result.add(
            "ALFA_AMOUNT_ARITHMETIC_MISMATCH",
            "; ".join(mismatches),
            group="amounts",
        )
    return result


# Bank Oracle/Quartz amounts group thousands with NBSP/NNBSP; SEQ edits often
# dump a bare digit run (≥4) or pad the RUR token with extra NBSP to keep
# content-stream length. Both are absent from the Alfa genuine corpus.
_BARE_AMOUNT_RE = re.compile(r"(?<!\d)\d{4,}[\s\u00a0\u202f]*RUR", re.IGNORECASE)
_RUR_PAD_RE = re.compile(r"RUR(?:\u00a0|\u202f){2,}", re.IGNORECASE)
_MASKED_CARD_RE = re.compile(r"(?<!\d)(\d{6})\*{4,8}(\d{4})(?!\d)")


def _payment_bin_ok(bin6: str) -> bool:
    """Alfa card-receipt BINs in the genuine corpus are MIR 2200xx only.

    Loose Visa/MC ranges previously accepted SEQ junk like 234567 / 456789
    (they fall inside Mastercard 2-series / Visa '4…').
    """
    if not (bin6.isdigit() and len(bin6) == 6):
        return False
    n = int(bin6)
    return 220_000 <= n <= 220_499  # MIR


_RUR_TOKEN_RE = re.compile(
    r"(\d(?:[\d\u00a0\u202f]*\d)?)\u00a0RUR(\u00a0|\u202f)?",
)


def validate_amount_typography(text: str) -> SemanticResult:
    result = SemanticResult()
    raw = text or ""
    bare = _BARE_AMOUNT_RE.findall(raw)
    if bare:
        result.add(
            "ALFA_AMOUNT_TYPOGRAPHY_ANOMALY",
            (
                "сумма без банковской группировки разрядов "
                f"(пример {bare[0]!r}; эталон: '4\\xa0875\\xa0RUR')"
            ),
            group="amounts",
        )
    if _RUR_PAD_RE.search(raw):
        result.add(
            "ALFA_AMOUNT_TYPOGRAPHY_ANOMALY",
            "хвостовой NBSP-padding после RUR — след подгонки длины content stream",
            group="amounts",
        )
    # Oracle BI always emits trailing NBSP after every «... RUR» token on SBP/
    # card shells. SEQ content rewrites that keep decoded /Contents length often
    # drop the trailing NBSP on the transfer-amount line while leaving fee intact
    # (or the reverse) — intra-document RUR token asymmetry, 0-FP on genuines.
    toks = [(m.group(0), m.group(2) is not None) for m in _RUR_TOKEN_RE.finditer(raw)]
    if len(toks) >= 2:
        trails = {has_trail for _tok, has_trail in toks}
        if len(trails) > 1:
            sample = ", ".join(repr(t) for t, _ in toks[:3])
            result.add(
                "ALFA_RUR_TRAILING_NBSP_ASYMMETRY",
                (
                    "часть RUR-токенов без хвостового NBSP при том что другие с ним "
                    f"(примеры: {sample}) — след подгонки длины content stream "
                    "при clone/rewrite Oracle shell"
                ),
                group="amounts",
            )
    return result


def validate_card_bins(text: str, method: str | None = None) -> SemanticResult:
    """SEQ card templates use sequential junk BINs (789012…); genuines use MIR/Visa/MC."""
    result = SemanticResult()
    method = method or classify_submethod(text)
    if method != METHOD_CARD:
        return result
    cards = _MASKED_CARD_RE.findall(text or "")
    result.stats["masked_cards"] = [f"{b}******{t}" for b, t in cards]
    bad = [b for b, _t in cards if not _payment_bin_ok(b)]
    if bad:
        result.add(
            "ALFA_CARD_BIN_INVALID",
            (
                f"BIN карты {bad[0]} вне MIR 2200xx (эталон Альфа card-квитанций) — "
                f"признак synthetic card template, не банк-эмиттер"
            ),
            group="fields",
        )
    # SEQ card tails reuse ABAB last4 (6161/5050/3838…). Absent from genuines.
    abab = [
        tail
        for _bin, tail in cards
        if len(tail) == 4
        and tail[0] == tail[2]
        and tail[1] == tail[3]
        and tail[0] != tail[1]
    ]
    if abab:
        result.add(
            "ALFA_CARD_LAST4_ABAB",
            (
                f"хвост карты {abab[0]} — паттерн ABAB; "
                f"в корпусе Альфа card-квитанций таких last4 нет — SEQ template"
            ),
            group="fields",
        )
    return result


# SEQ reassembly dumps gibberish Cyrillic names / landline-looking phones / ladder
# debit accounts. Corpus (Alfa genuines): party consonant-run ≤3, recipient phone
# DEF always 9xx when present, debit-account ascending-digit score ≤5.
_CYRILLIC_VOWELS = frozenset("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_DEBIT_ACCOUNT_SEQ_HARD = 8
_PHONE_RE = re.compile(r"\+7\s*\((\d{3})\)\s*\d{3}-\d{2}-\d{2}")
_MASKED_PHONE_RE = re.compile(r"(?<!\d)(\d{3})\*{3}(\d{4})(?!\d)")
_DEBIT_ACCOUNT_RE = re.compile(
    r"(?i)сч[её]т\s+списания\s*[:\s]*?(408\d{17})"
)
_MASKED_DEBIT_ACCOUNT_RE = re.compile(
    r"(?i)сч[её]т\s+списания\s*[:\s]*?(408178\*+\d{4})"
)
_DEBIT_ACCOUNT_EMPTY_RE = re.compile(
    r"(?im)^[ \t]*сч[её]т\s+списания[ \t]*$"
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


def _ascending_digit_score(account: str) -> int:
    digits = [int(ch) for ch in account if ch.isdigit()]
    return sum(1 for i in range(len(digits) - 1) if digits[i + 1] - digits[i] == 1)


def _max_cyrillic_alphabet_run(value: str) -> int:
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


def _extract_recipient_name(text: str) -> str:
    lines = (text or "").replace("\xa0", " ").replace("\u202f", " ").splitlines()
    for index, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("получатель"):
            inline = line.split(":", 1)
            if len(inline) == 2 and inline[1].strip():
                return inline[1].strip()
            for value in lines[index + 1 : index + 5]:
                candidate = value.strip()
                if candidate and not candidate.lower().startswith(
                    ("номер", "банк", "счёт", "счет", "телефон", "идентификатор")
                ):
                    return candidate
    return ""


def _extract_recipient_raw_line(text: str) -> str:
    """Recipient value line with trailing spaces preserved (pad artifact)."""
    lines = (text or "").replace("\xa0", " ").replace("\u202f", " ").splitlines()
    for index, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("получатель"):
            inline = line.split(":", 1)
            if len(inline) == 2 and inline[1].strip():
                return inline[1].rstrip("\r\n")
            for value in lines[index + 1 : index + 5]:
                if value.strip():
                    return value.rstrip("\r\n")
    return ""


def validate_field_artifacts(text: str) -> SemanticResult:
    """Structural field tells of SEQ reassembly — not novelty / atlas pins."""
    result = SemanticResult()
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")

    phone = _PHONE_RE.search(raw)
    if phone:
        def_code = phone.group(1)
        result.stats["recipient_phone_def"] = def_code
        if not def_code.startswith("9"):
            result.add(
                "ALFA_PHONE_DEF_NOT_MOBILE",
                (
                    f"телефон получателя DEF={def_code} (не 9xx); "
                    f"в корпусе Альфа мобильный получатель всегда 9xx — "
                    f"синтетический номер в SEQ-шаблоне"
                ),
                group="fields",
            )

    masked_phone = _MASKED_PHONE_RE.search(raw)
    if masked_phone:
        prefix = masked_phone.group(1)
        result.stats["masked_phone_prefix"] = prefix
        result.stats["masked_phone"] = masked_phone.group(0)
        if not prefix.startswith("9"):
            result.add(
                "ALFA_MASKED_PHONE_DEF_NOT_MOBILE",
                (
                    f"маскированный телефон {masked_phone.group(0)}: "
                    f"prefix={prefix} (не 9xx); в корпусе Альфа phone-квитанций "
                    f"маскированный DEF всегда 9xx — SEQ phone-template"
                ),
                group="fields",
            )

    recipient_raw = _extract_recipient_raw_line(raw)
    recipient = recipient_raw.strip()
    # Trailing spaces after recipient initials appear on genuines — never HARD.
    if recipient:
        run = _max_cyrillic_consonant_run(recipient)
        alpha = _max_cyrillic_alphabet_run(recipient)
        letters = sum(
            1
            for ch in recipient
            if ("А" <= ch <= "я") or ch in "Ёё"
        )
        initials = re.findall(r"[А-ЯЁ]\.", recipient)
        result.stats["recipient_name"] = recipient
        result.stats["recipient_consonant_run"] = run
        result.stats["recipient_alphabet_run"] = alpha
        result.stats["recipient_initials"] = len(initials)
        # Party consonant/alphabet-run HARDs removed — gibberish-name heuristics
        # (not structural); keep stats only.
        # Phone-method genuines mask as «Фам**в Д. В.» (two initials).
        # SEQ phone templates emit a single trailing initial («… О.»).
        if masked_phone and "**" in recipient and len(initials) == 1:
            result.add(
                "ALFA_PHONE_RECIPIENT_INITIALS",
                (
                    f"получатель {recipient!r}: одна инициаль при маскированном "
                    f"phone-методе; в корпусе всегда две («Д. В.») — "
                    f"SEQ phone-template"
                ),
                group="fields",
            )
        # Masked phone (923***5074) always pairs with masked surname (Вол**в …)
        # on genuines. SEQ leaves a fully visible FIO beside the mask.
        if masked_phone and "**" not in recipient:
            result.add(
                "ALFA_PHONE_NAME_UNMASKED",
                (
                    f"маскированный телефон {masked_phone.group(0)} при открытом "
                    f"ФИО {recipient!r}; в корпусе phone-квитанций фамилия тоже "
                    f"с «**» — SEQ phone-template"
                ),
                group="fields",
            )

    # Empty debit account (whitespace-only value) — absent from genuines.
    if _DEBIT_ACCOUNT_EMPTY_RE.search(raw):
        lines = raw.splitlines()
        for index, line in enumerate(lines):
            if re.match(r"(?i)^[ \t]*сч[её]т\s+списания[ \t]*$", line):
                nxt = ""
                for value in lines[index + 1 : index + 4]:
                    if value.strip():
                        nxt = value.strip()
                        break
                if not nxt or set(nxt) <= {"*", "•", "."}:
                    # blank / only bullets — catch fully empty next
                    pass
                # If next non-empty is another label, account value is empty.
                if not nxt or nxt.lower().startswith(
                    ("идентификатор", "сообщение", "банк", "номер", "комиссия")
                ):
                    result.add(
                        "ALFA_DEBIT_ACCOUNT_EMPTY",
                        "счёт списания пуст — SEQ shell без account field",
                        group="fields",
                    )
                break

    account_m = _DEBIT_ACCOUNT_RE.search(raw)
    if account_m:
        account = account_m.group(1)
        score = _ascending_digit_score(account)
        result.stats["debit_account"] = account
        result.stats["debit_account_seq_score"] = score
        if score >= _DEBIT_ACCOUNT_SEQ_HARD:
            result.add(
                "ALFA_DEBIT_ACCOUNT_SEQUENTIAL",
                (
                    f"счёт списания {account}: ascending-digit score={score} "
                    f"(HARD≥{_DEBIT_ACCOUNT_SEQ_HARD}; корпус ≤5) — "
                    f"лестничный synthetic 40817…, не банк-эмиттер"
                ),
                group="fields",
            )
        # SEQ Oracle shells mint 408178 + 14-digit body as a window into a
        # repeating 10-digit seed (e.g. 1537597193→15375971931537). Genuines: 0.
        body = account[6:] if account.startswith("408178") else ""
        if len(body) == 14 and all(
            body[i] == body[i + 10] for i in range(4)
        ):
            result.add(
                "ALFA_DEBIT_ACCOUNT_PERIODIC",
                (
                    f"счёт списания {account}: 14-digit body is a period-10 "
                    f"cyclic window — synthetic SEQ account ladder"
                ),
                group="fields",
            )
    else:
        masked_acct = _MASKED_DEBIT_ACCOUNT_RE.search(raw)
        if masked_acct:
            account = masked_acct.group(1)
            last4 = account[-4:]
            score = _ascending_digit_score(last4)
            result.stats["debit_account_masked"] = account
            result.stats["debit_account_last4_seq_score"] = score
            # Genuines use real last4 (e.g. 0922, score 0). SEQ templates emit
            # ladder tails 0123/2345/4567 (score 3).
            if score >= 3:
                result.add(
                    "ALFA_DEBIT_ACCOUNT_SEQUENTIAL",
                    (
                        f"маскированный счёт {account}: last4 ascending "
                        f"score={score} — лестничный хвост SEQ-шаблона"
                    ),
                    group="fields",
                )
    return result


def run_semantic_checks(
    text: str,
    emitter_evidence: EmitterEvidence | None = None,
) -> SemanticResult:
    """Convenience aggregator; classification always precedes contracts."""
    method = classify_submethod(text)
    parts: Iterable[SemanticResult] = (
        validate_field_contract(text, method),
        validate_operation_ids(text, method),
        validate_field_value_binding(text, method),
        validate_amount_arithmetic(text),
        validate_amount_typography(text),
        validate_card_bins(text, method),
        validate_field_artifacts(text),
    )
    result = SemanticResult(stats={"method": method})
    if emitter_evidence is not None:
        emitter = classify_emitter(emitter_evidence)
        result.flags.extend(emitter.flags)
        result.stats.update(emitter.stats)
    for part in parts:
        result.flags.extend(part.flags)
        result.stats.update(part.stats)
    return result
