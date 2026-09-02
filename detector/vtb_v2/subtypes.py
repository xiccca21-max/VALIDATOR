"""VTB v2 subtype routing and fieldset contracts."""

from __future__ import annotations

import re
import unicodedata

from .rules import (
    PROFILE_RULES_ENABLED,
    SUBTYPE_CARD,
    SUBTYPE_LABELS,
    SUBTYPE_PHONE,
    SUBTYPE_SBP,
    SUBTYPE_SBP_ACCOUNT,
    SUBTYPE_UNKNOWN,
    VTB_BANK_ALIASES,
)
from .types import VtbFlag

_HYPHENS = (
    "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212",
    "\uFE58", "\uFE63", "\uFF0D",
)


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\xa0", " ").replace("\u202f", " ")
    for h in _HYPHENS:
        t = t.replace(h, "-")
    return t


def _low(text: str) -> str:
    return normalize_text(text).lower()


def is_vtb_receipt(text: str, pdf_bytes: bytes) -> bool:
    low = _low(text)
    if any(m in low for m in (
        "банк втб", "втб (пао)", "втб(пао)",
        "исходящий перевод сбп",
        "перевод на карту",
        "по номеру телефона клиенту втб",
        "перевод на счет другому лицу",
        "перевод на счёт другому лицу",
        "денежный перевод",
    )):
        return True
    return b"openhtmltopdf" in pdf_bytes.lower() and (
        b"\xd0\x92\xd0\xa2\xd0\x91" in pdf_bytes or "втб" in low
    )


def classify_subtype(text: str) -> str:
    low = _low(text)
    # OpenPDF 2.x account-SBP (A4 / Arial) — distinct from openhtml «Исходящий перевод СБП».
    if (
        "перевод на счет другому лицу" in low
        or "перевод на счёт другому лицу" in low
    ) and "сбп" in low:
        return SUBTYPE_SBP_ACCOUNT
    if "исходящий перевод сбп" in low:
        return SUBTYPE_SBP
    # Official card title is two lines; forgeries often drop «Денежный перевод».
    if "перевод на карту" in low:
        return SUBTYPE_CARD
    if "по номеру телефона клиенту втб" in low:
        return SUBTYPE_PHONE
    if "банк втб" in low or "втб (пао)" in low:
        return SUBTYPE_UNKNOWN
    return SUBTYPE_UNKNOWN


def subtype_label(code: str) -> str:
    return SUBTYPE_LABELS.get(code, code)


def _has_label(low: str, *labels: str) -> bool:
    return any(lab in low for lab in labels)


def field_presence(text: str) -> dict[str, bool]:
    low = _low(text)
    return {
        "status": _has_label(low, "статус"),
        "op_date": _has_label(low, "дата операции"),
        "debit_account": _has_label(low, "счет списания", "счёт списания"),
        "payer_name": _has_label(low, "имя плательщика"),
        "receiver": _has_label(low, "получатель"),
        "receiver_phone": _has_label(low, "телефон получателя"),
        "receiver_bank": _has_label(low, "банк получателя"),
        "sbp_id": _has_label(low, "id операции в сбп", "id операции"),
        "amount": _has_label(low, "сумма операции"),
        "credit_amount": _has_label(low, "сумма зачисления"),
        "phone_number": _has_label(low, "номер телефона"),
        "executed_stamp": _has_label(low, "исполнено"),
        "transfer_type": _has_label(low, "тип перевода"),
        "card_number": _has_label(low, "номер карты"),
        "receiver_card": _has_label(low, "карта получателя"),
        "receiver_account": _has_label(low, "счет получателя", "счёт получателя"),
        "sender": _has_label(low, "отправитель"),
        "commission": _has_label(low, "комиссия"),
        "amount_with_commission": _has_label(low, "сумма с комиссией"),
        "money_transfer_title": _has_label(low, "денежный перевод"),
    }


_REQUIRED: dict[str, tuple[str, ...]] = {
    SUBTYPE_SBP: (
        "status", "op_date", "debit_account", "payer_name", "receiver",
        "receiver_phone", "receiver_bank", "sbp_id", "amount",
    ),
    SUBTYPE_CARD: (
        "status", "op_date", "card_number", "debit_account", "payer_name",
        "receiver_card", "receiver_bank", "amount",
    ),
    SUBTYPE_PHONE: (
        "status", "op_date", "debit_account", "receiver", "receiver_phone",
        "receiver_account", "sender", "amount",
    ),
    SUBTYPE_SBP_ACCOUNT: (
        "status", "debit_account", "receiver_account", "receiver",
        "receiver_bank", "sbp_id", "credit_amount", "executed_stamp",
    ),
}

_FORBIDDEN: dict[str, tuple[str, ...]] = {
    SUBTYPE_SBP: ("receiver_card", "receiver_account"),
    # Official card profile has no commission block and no SBP/phone fields.
    SUBTYPE_CARD: (
        "sbp_id", "receiver_phone", "receiver_account",
        "commission", "amount_with_commission",
    ),
    SUBTYPE_PHONE: ("sbp_id", "receiver_bank", "receiver_card"),
    # Account-SBP is a different generator: full receiver account, no payer-name block.
    SUBTYPE_SBP_ACCOUNT: ("receiver_card", "payer_name", "money_transfer_title"),
}


def _card_mask_key(raw: str) -> tuple[str, str] | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < 10:
        return None
    return digits[:6], digits[-4:]


def extract_card_mask_pair(text: str) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Return (sender_card_mask, receiver_card_mask) from labeled fields."""
    raw = normalize_text(text)
    sender = receiver = None
    m_send = re.search(
        r"номер карты\s*([0-9**\s]+)",
        raw,
        flags=re.IGNORECASE,
    )
    m_recv = re.search(
        r"карта получателя\s*([0-9**\s]+)",
        raw,
        flags=re.IGNORECASE,
    )
    if m_send:
        sender = _card_mask_key(m_send.group(1))
    if m_recv:
        receiver = _card_mask_key(m_recv.group(1))
    return sender, receiver


def extract_receiver_bank(text: str) -> str:
    raw = normalize_text(text)
    low = raw.lower()
    idx = low.find("банк получателя")
    if idx < 0:
        return ""
    chunk = raw[idx:idx + 120]
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return lines[1]
    # same-line value
    m = re.search(r"банк получателя\s*[:\-]?\s*(.+)", low)
    return (m.group(1).strip() if m else "")[:80]


def normalize_bank_name(value: str) -> str:
    v = _low(value)
    v = re.sub(r"[\"'«»]", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    v = re.sub(r"\(пао\)", "пао", v)
    v = re.sub(r"\s+пао$", " пао", v).strip()
    # strip trailing punctuation
    v = v.strip(" .,;")
    return v


def is_vtb_bank(value: str) -> bool:
    norm = normalize_bank_name(value)
    if not norm:
        return False
    if norm in VTB_BANK_ALIASES:
        return True
    # allow "банк втб (пао)" style already normalized
    compact = norm.replace(" ", "")
    aliases_compact = {a.replace(" ", "") for a in VTB_BANK_ALIASES}
    return compact in aliases_compact


def profile_rule_enabled(profile_version: str, code: str) -> bool:
    enabled = PROFILE_RULES_ENABLED.get(profile_version)
    if enabled is None:
        return False
    return code in enabled


def check_method_hard_rules(
    text: str,
    *,
    subtype: str,
    profile_version: str = "vtb_openhtml_v1",
) -> list[VtbFlag]:
    """HARD method contradictions — gated by versioned profile."""
    flags: list[VtbFlag] = []
    fields = field_presence(text)
    low = _low(text)
    receiver_bank = extract_receiver_bank(text)
    bank_is_vtb = is_vtb_bank(receiver_bank)

    if (
        profile_rule_enabled(profile_version, "VTB_METHOD_SBP_TO_SELF_BANK")
        and subtype == SUBTYPE_SBP_ACCOUNT
        and bank_is_vtb
    ):
        flags.append(VtbFlag(
            code="VTB_METHOD_SBP_TO_SELF_BANK",
            detail=(
                f"СБП на счёт в другом банке, но банк получателя "
                f"«{receiver_bank}» нормализован как ВТБ — конфликт метода"
            ),
            tier="HARD",
            group="semantic_method",
            rule_id="VTB_METHOD_SBP_TO_SELF_BANK",
        ))

    if (
        profile_rule_enabled(profile_version, "VTB_METHOD_SBP_TO_SELF_BANK")
        and subtype == SUBTYPE_SBP
        and bank_is_vtb
        and "исходящий перевод сбп" in low
    ):
        flags.append(VtbFlag(
            code="VTB_METHOD_SBP_TO_SELF_BANK",
            detail=(
                f"исходящий СБП на банк получателя «{receiver_bank}» "
                f"(нормализован как ВТБ) — конфликт метода"
            ),
            tier="HARD",
            group="semantic_method",
            rule_id="VTB_METHOD_SBP_TO_SELF_BANK",
        ))

    if profile_rule_enabled(profile_version, "VTB_METHOD_FIELDSET_COLLISION"):
        if (
            bank_is_vtb
            and "исходящий перевод сбп" in low
            and fields.get("sbp_id")
            and not fields.get("receiver_account")
            and not fields.get("sender")
            and subtype != SUBTYPE_PHONE
        ):
            flags.append(VtbFlag(
                code="VTB_METHOD_FIELDSET_COLLISION",
                detail=(
                    "fieldset СБП→ВТБ без счёта получателя и без внутреннего "
                    "отправителя — конфликт с профилем перевода"
                ),
                tier="HARD",
                group="semantic_method",
                rule_id="VTB_METHOD_FIELDSET_COLLISION",
            ))

    # Forbidden fields for exact subtype → method collision HARD
    forbidden = _FORBIDDEN.get(subtype, ())
    for key in forbidden:
        if fields.get(key):
            flags.append(VtbFlag(
                code="VTB_METHOD_FIELDSET_COLLISION",
                detail=f"запрещённое для {subtype} поле «{key}» присутствует",
                tier="HARD",
                group="semantic_method",
                rule_id="VTB_METHOD_FIELDSET_COLLISION",
            ))
            break

    if (
        profile_rule_enabled(profile_version, "VTB_CARD_TITLE_GRAMMAR")
        and subtype == SUBTYPE_CARD
        and "перевод на карту" in low
        and not fields.get("money_transfer_title")
    ):
        flags.append(VtbFlag(
            code="VTB_CARD_TITLE_GRAMMAR",
            detail=(
                "карточный чек без заголовка «Денежный перевод» "
                "(штатный openhtml-профиль ВТБ всегда двухстрочный)"
            ),
            tier="HARD",
            group="semantic_method",
            rule_id="VTB_CARD_TITLE_GRAMMAR",
        ))

    if profile_rule_enabled(profile_version, "VTB_CARD_SENDER_RECEIVER_SAME"):
        sender_mask, recv_mask = extract_card_mask_pair(text)
        if (
            subtype == SUBTYPE_CARD
            and sender_mask
            and recv_mask
            and sender_mask == recv_mask
        ):
            flags.append(VtbFlag(
                code="VTB_CARD_SENDER_RECEIVER_SAME",
                detail=(
                    f"«Номер карты» и «Карта получателя» совпадают "
                    f"(BIN {sender_mask[0]} / last4 {sender_mask[1]}) — "
                    f"перевод карты на саму себя"
                ),
                tier="HARD",
                group="semantic_method",
                rule_id="VTB_CARD_SENDER_RECEIVER_SAME",
            ))

    return flags


def check_required_fields_diagnostic(text: str, subtype: str) -> list[VtbFlag]:
    """Missing optional extras never FAKE; missing required → diagnostic only
    unless combined with method collision (handled elsewhere)."""
    if subtype not in _REQUIRED:
        return []
    fields = field_presence(text)
    missing = [k for k in _REQUIRED[subtype] if not fields.get(k)]
    if not missing:
        return []
    return [VtbFlag(
        code="VTB_REQUIRED_FIELD_OBSERVATION",
        detail=f"отсутствуют поля профиля {subtype}: {', '.join(missing)}",
        tier="DIAGNOSTIC",
        rule_id="VTB_REQUIRED_FIELD_OBSERVATION",
    )]
