"""
T-Bank PDF receipt parser.
Extracts structured fields from text blocks and determines check type.
"""

import re
import fitz

from .corpus_profiles import CHANNEL_CARD, CHANNEL_PHONE, CHANNEL_SBP, detect_receipt_channel
from .recipient_bank import extract_recipient_bank_fields

_TBANK_NAMES = {"т-банк", "тинькофф", "tinkoff", "tbank", "t-bank", "т банк"}


def _get_blocks(pdf_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    blocks = []
    for page in doc:
        for b in page.get_text("blocks"):
            txt = b[4].strip()
            if txt:
                blocks.append(txt)
    doc.close()
    return blocks


def _find_block_value(blocks: list[str], label: str) -> str | None:
    """Find value in block formatted as 'LABEL\\nVALUE'."""
    for b in blocks:
        lines = b.split("\n")
        if len(lines) >= 2 and lines[0].strip() == label:
            return lines[1].strip()
    return None


def _find_block_key(blocks: list[str], label: str) -> str | None:
    """Find value in block formatted as 'VALUE\\nLABEL'."""
    for b in blocks:
        lines = b.split("\n")
        if len(lines) >= 2 and lines[-1].strip() == label:
            return lines[0].strip()
    return None


def _clean_amount(raw: str) -> str:
    """'5 000 i' → '5 000,00 руб.'"""
    cleaned = re.sub(r'[^\d\s]', '', raw).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned:
        try:
            num = int(cleaned.replace(' ', ''))
            return f"{num:,}".replace(',', ' ') + ",00 руб."
        except ValueError:
            return cleaned + " руб."
    return raw


def _check_title(transfer: str, receiver_bank: str, is_sbp: bool) -> str:
    bank_lower = receiver_bank.lower() if receiver_bank else ""
    is_same_bank = any(n in bank_lower for n in _TBANK_NAMES)

    if is_same_bank:
        return "Чек Т-Банка"
    if is_sbp:
        return "СБП Т-Банк"
    if "карт" in transfer.lower():
        return "Чек Т-Банка по номеру карты"
    if "телефон" in transfer.lower():
        return "Чек Т-Банка по номеру телефона"
    return "Чек Т-Банка"


def parse(pdf_bytes: bytes) -> dict:
    """
    Returns dict with fields:
        title, sender, receiver, receiver_account,
        receiver_bank, status, receiver_contact,
        contact_label, amount, is_sbp, raw_blocks
    """
    blocks = _get_blocks(pdf_bytes)

    # Amount — from first block: 'DD.MM.YYYY  HH:MM:SS\\nИтого\\n5 000 i'
    amount_raw = ""
    for b in blocks:
        lines = b.split("\n")
        if "Итого" in lines and len(lines) >= 3:
            amount_raw = lines[2].strip()
            break
    if not amount_raw:
        amount_raw = _find_block_key(blocks, "Сумма") or ""

    # Transfer type
    transfer = _find_block_value(blocks, "Перевод") or ""

    # Status
    status = _find_block_value(blocks, "Статус") or "—"

    # Sender — block 'NAME\\nОтправитель'
    sender = _find_block_key(blocks, "Отправитель") or "—"

    # Receiver — block 'Получатель\\nNAME'
    receiver = _find_block_value(blocks, "Получатель") or "—"

    # Receiver bank — label-aware only (never issuer / SBP fallback).
    bank_fields = extract_recipient_bank_fields(pdf_bytes, "\n".join(blocks), issuer_bank="Т-Банк")
    receiver_bank = bank_fields.get("recipient_bank_normalized") or "—"

    # Receiver phone
    receiver_phone = _find_block_value(blocks, "Телефон получателя")

    # Receiver card
    receiver_card = _find_block_value(blocks, "Карта получателя") or \
                    _find_block_value(blocks, "Номер карты получателя")

    # Receiver account (last 4 digits)
    receiver_account = _find_block_value(blocks, "Счет получателя")
    if not receiver_account and receiver_card:
        # Extract last 4 digits from card number
        m = re.search(r'(\d{4})\s*$', receiver_card)
        if m:
            receiver_account = m.group(1)
    if not receiver_account and receiver_phone:
        # Last 2 digits of phone as short account hint
        m = re.search(r'(\d{2})\s*$', receiver_phone.replace(' ', '').replace('-', ''))
        if m:
            receiver_account = None  # don't show phone digits as account

    # SBP indicator
    is_sbp = False
    flat_lower = "\n".join(blocks).lower()
    if any(m in flat_lower for m in (
        "идентификатор операции",
        "id операции сбп",
        "id операции в сбп",
        "номер операции в сбп",
    )):
        is_sbp = True
    else:
        for b in blocks:
            lines = [l.strip() for l in b.split("\n")]
            if "Идентификатор операции" in lines and "СБП" in lines:
                is_sbp = True
                break

    # Contact label and value
    if receiver_phone:
        contact_label = "Телефон получ"
        contact_value = receiver_phone
    elif receiver_card:
        contact_label = "Карта получ"
        contact_value = receiver_card
    else:
        contact_label = None
        contact_value = None

    title = _check_title(transfer, receiver_bank, is_sbp)
    transfer_channel = detect_receipt_channel("\n".join(blocks))

    def _or_none(v):
        return v if v and v != "—" else None

    return {
        "title":            title,
        "sender":           _or_none(sender),
        "receiver":         _or_none(receiver),
        "receiver_account": _or_none(receiver_account),
        "receiver_bank":    _or_none(receiver_bank),
        "status":           _or_none(status),
        "contact_label":    contact_label,
        "contact_value":    _or_none(contact_value),
        "amount":           _clean_amount(amount_raw) or None,
        "is_sbp":           is_sbp,
        "transfer_channel": transfer_channel,
        "issuer_bank": bank_fields["issuer_bank"],
        "recipient_bank_raw": bank_fields["recipient_bank_raw"],
        "recipient_bank_normalized": bank_fields["recipient_bank_normalized"],
        "recipient_bank_source": bank_fields["recipient_bank_source"],
        "sbp_route_profile": bank_fields["sbp_route_profile"],
        "fields": {
            "issuer_bank": bank_fields["issuer_bank"],
            "recipient_bank_raw": bank_fields["recipient_bank_raw"],
            "recipient_bank_normalized": bank_fields["recipient_bank_normalized"],
            "recipient_bank_source": bank_fields["recipient_bank_source"],
        },
    }


def _f(label: str, value) -> str | None:
    """Return 'Label: value' or None if value is absent/dash."""
    v = (value or "").strip() if isinstance(value, str) else (value or "")
    if not v or v == "—":
        return None
    return f"{label}: {v}"


def _issuer_key(name: str) -> str:
    n = (name or "").lower().replace("ё", "е")
    if "альфа" in n or "alfa" in n:
        return "alfa"
    if "сбер" in n:
        return "sber"
    if "озон" in n or "ozon" in n:
        return "ozon"
    if "промсвязь" in n or n.strip() in {"псб", "psb"} or "псб" in n:
        return "psb"
    if "санкт-петербург" in n or "бспб" in n or "банк \"санкт" in n:
        return "bspb"
    if "газпром" in n:
        return "gpb"
    if "т-банк" in n or "тинькофф" in n or "tbank" in n:
        return "tbank"
    return ""


def _format_visibility(parsed: dict) -> dict[str, bool]:
    """Which TG lines to show for this issuer / channel."""
    bank = _issuer_key(parsed.get("issuer_bank") or "")
    ch = (parsed.get("transfer_channel") or "").lower()
    op = (parsed.get("operation") or "").lower().replace("ё", "е")
    show = {
        "sender": True,
        "sender_card": True,
        "receiver": True,
        "receiver_account": True,
        "bank": True,
        "status": True,
        "contact": True,
        "amount": True,
    }
    if bank == "alfa":
        if ch == "card":
            return {
                "sender": False, "sender_card": True, "receiver": False,
                "receiver_account": False, "bank": False, "status": False,
                "contact": True, "amount": True,
            }
        if ch == "phone":
            return {
                "sender": False, "sender_card": False, "receiver": True,
                "receiver_account": False, "bank": False, "status": False,
                "contact": True, "amount": True,
            }
        # SBP (and default Alfa)
        show["sender"] = False
        show["sender_card"] = False
    elif bank == "bspb":
        show["sender"] = False
        show["sender_card"] = False
    elif bank == "ozon":
        show["bank"] = False
        if ch == "card":
            show["sender"] = False
            show["sender_card"] = False
        elif ch == "phone":
            show["sender_card"] = False
    elif bank == "psb" and ch == "sbp":
        show["sender"] = False
        show["sender_card"] = False
    elif bank == "sber":
        if "клиенту сбер" in op or ch == "intrabank":
            show["bank"] = False
    return show


def format_receipt(parsed: dict) -> str:
    """Format parsed fields — only lines with real values, bank-aware."""
    show = _format_visibility(parsed)
    recipient = (
        (parsed.get("recipient_bank_normalized") or "").strip()
        or ((parsed.get("fields") or {}).get("recipient_bank_normalized") or "").strip()
        or (parsed.get("receiver_bank") or "").strip()
    )
    rows: list[str] = []
    if show["sender"]:
        rows.append(_f("Отпр", parsed.get("sender")))
    if show["sender_card"]:
        rows.append(_f("Карта отпр", parsed.get("sender_card")))
    if show["receiver"]:
        rows.append(_f("Получ", parsed.get("receiver")))
    if show["receiver_account"]:
        rows.append(_f("Счет получ", parsed.get("receiver_account")))
    if show["bank"] and recipient:
        rows.append(f"Банк получ: {recipient}")
    if show["status"]:
        rows.append(_f("Статус", parsed.get("status")))
    if show["contact"] and parsed.get("contact_label") and parsed.get("contact_value"):
        rows.append(_f(parsed["contact_label"], parsed["contact_value"]))
    elif show["contact"] and parsed.get("receiver_card"):
        rows.append(_f("Карта получ", parsed.get("receiver_card")))
    if show["amount"]:
        rows.append(_f("Сумма", parsed.get("amount")))
    return "\n".join(r for r in rows if r)


# ── Generic, bank-agnostic receipt parser ──────────────────────────────────────
# Works off the plain text by matching common Russian field labels, so it covers
# every bank regardless of PDF layout.

_SENDER_LABELS = [
    "Ф.И.О. отправителя", "ФИО отправителя", "Отправитель", "Плательщик",
    "ФИО плательщика", "Имя отправителя",
]
_RECEIVER_LABELS = [
    "ФИО получателя перевода", "Получатель перевода", "ФИО получателя",
    "Получатель", "Имя получателя", "Кому",
]
_RBANK_LABELS = [
    "Банк получателя", "Банк-получатель", "Банк зачисления",
    "Наименование банка получателя",
]
_STATUS_LABELS = ["Статус операции", "Статус перевода", "Статус", "Состояние"]
_PHONE_LABELS = [
    "Номер телефона получателя", "Телефон получателя", "Номер телефона",
]
_CARD_LABELS = [
    "Карта получателя", "Номер карты получателя", "Карта зачисления",
]
_SENDER_CARD_LABELS = [
    "Номер источника списания", "Номер карты отправителя", "Карта отправителя",
    "Карта списания",
]
_RECEIVER_CARD_LABELS = [
    "Реквизиты карты получателя", "Номер карты получателя", "Карта получателя",
    "Карта зачисления", "На карту другого банка", "На карту", "Номер карты",
]
_AMOUNT_LABELS = ["Сумма перевода", "Сумма операции", "Сумма платежа", "Сумма", "Итого"]
_OPERATION_LABELS = ["Операция", "Тип операции", "Назначение платежа"]

_OK_WORDS = ("успеш", "выполн", "исполн", "заверш", "проведен", "проведён", "обработан")
_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
    r"\s*(?:₽|руб\.?|р\.?|RUB|RUR)\b",
    re.I,
)
_PHONE_RE = re.compile(r"\+?7[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
_CARD_RE = re.compile(r"(?:\*{2,}|•{2,}|\d{4})[\s\*•]*\d{4}\b")


def _lines(text: str) -> list[str]:
    """All lines including empty ones — needed to handle blank separator rows.
    Normalises non-breaking spaces so labels match regardless of PDF encoding."""
    return [l.replace("\xa0", " ").strip() for l in (text or "").splitlines()]


def _next_nonempty(lines: list[str], after: int) -> str | None:
    """Return first non-empty line after index `after`."""
    for j in range(after + 1, min(after + 4, len(lines))):
        v = lines[j].strip()
        if v and not v.endswith(":"):
            return v
    return None


def _prev_nonempty(lines: list[str], before: int) -> str | None:
    for j in range(before - 1, max(before - 4, -1), -1):
        v = lines[j].strip()
        if v and not v.endswith(":"):
            return v
    return None


def _sorted_labels(labels: list[str]) -> list[str]:
    return sorted(labels, key=len, reverse=True)


def _is_bank_footer_line(line: str) -> bool:
    low = (line or "").lower()
    return any(x in low for x in (
        "gazprombank", "mailbox@", "www.", "e-mail", "инфолиния",
        "клиентская поддержка",
    )) or (
        low.startswith("телефон:") and "получател" not in low
    )


def _looks_like_op_type(s: str) -> bool:
    low = (s or "").lower().replace("ё", "е")
    return low.startswith("перевод") or "по сбп" in low


def _looks_like_person_name(s: str) -> bool:
    if not s or _PHONE_RE.search(s) or _looks_like_op_type(s):
        return False
    digits = sum(c.isdigit() for c in s)
    if digits >= 8:
        return False
    return sum(c.isalpha() for c in s) >= 5


def _is_accountish(s: str) -> bool:
    low = (s or "").lower().replace("ё", "е")
    if "основной счет" in low or "счет" == low or "счёт" == low:
        return True
    if "основной счёт" in low:
        return True
    return sum(c.isdigit() for c in s) >= 10


def _val(
    lines: list[str],
    labels: list[str],
    *,
    skip_footer: bool = False,
) -> str | None:
    """Find a field value: 'Label: value', 'Label value', or label then
    next non-empty line (handles blank separator lines like Alfa-Bank)."""
    low = [l.lower() for l in lines]
    for lab in _sorted_labels(labels):
        ll = lab.lower()
        for i, line in enumerate(low):
            if skip_footer and _is_bank_footer_line(lines[i]):
                continue
            if line == ll or line == ll + ":":
                v = _next_nonempty(lines, i)
                if v:
                    return v
                continue
            if line.startswith(ll):
                remainder = lines[i][len(lab):].lstrip()
                if remainder.startswith(":"):
                    rest = remainder[1:].lstrip(" \t—-")
                    if rest and not rest.endswith(":"):
                        return rest.strip()
                elif not remainder:
                    v = _next_nonempty(lines, i)
                    if v:
                        return v
    return None


def _val_person(lines: list[str], labels: list[str]) -> str | None:
    """Person name: supports both LABEL\\nVALUE and VALUE\\nLABEL (Sber SBP)."""
    low = [l.lower() for l in lines]
    for lab in _sorted_labels(labels):
        ll = lab.lower()
        for i, line in enumerate(low):
            if line != ll and line != ll + ":":
                continue
            nxt = _next_nonempty(lines, i)
            prev = _prev_nonempty(lines, i)
            if nxt and _looks_like_person_name(nxt):
                return nxt
            if prev and _looks_like_person_name(prev):
                return prev
            if nxt and not _looks_like_op_type(nxt) and not _is_accountish(nxt):
                return nxt
    return None


def _detect_generic_channel(text: str) -> str:
    t = (text or "").lower().replace("\xa0", " ").replace("ё", "е")
    if any(x in t for x in (
        "номер операции в сбп", "id операции сбп", "идентификатор операции в сбп",
        "идентификатор операции", "перевод по сбп", "по сбп",
        "системы быстрых платежей", "систему быстрых платежей",
    )):
        return "sbp"
    if "клиенту сбер" in t:
        return "intrabank"
    if "клиенту альфа" in t:
        return "phone"
    if "с карты на карту" in t or "номер карты отправителя" in t:
        return "card"
    if "номер карты получателя" in t and "телефон" not in t:
        return "card"
    if "номер телефона получателя" in t or "телефон получателя" in t:
        return "phone"
    return "other"


_GPB_MARKERS = (
    "gazprombank.ru",
    "mailbox@gazprombank",
    "mailbox@gazprombank.ru",
)


def _is_gpb_receipt(text: str) -> bool:
    """Issuer detection only — never use recipient-bank wording."""
    low = (text or "").lower()
    if any(m in low for m in _GPB_MARKERS):
        return True
    # Legal issuer footer, not recipient bank mentions.
    return "акционерное общество" in low and "газпромбанк" in low


def _parse_gpb_pairs(lines: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for i, line in enumerate(lines):
        if not line.endswith(":"):
            continue
        label = line[:-1].strip()
        if not label or _is_bank_footer_line(line):
            continue
        v = _next_nonempty(lines, i)
        if v and not v.endswith(":"):
            pairs[label] = v
    return pairs


def _format_amount(raw: str) -> str | None:
    s = (raw or "").replace("\u00a0", " ").strip()
    # US-style thousands: 30,500.00 ₽
    m_us = re.search(
        r"(\d{1,3}(?:,\d{3})+)(?:\.(\d{2}))?\s*(?:₽|руб\.?|р\.?|RUB|RUR)?",
        s,
        re.I,
    )
    if m_us:
        whole = m_us.group(1).replace(",", " ")
        frac = m_us.group(2) or "00"
        return f"{whole},{frac} руб."
    m = _AMOUNT_RE.search(s)
    if m:
        return m.group(1).replace("\u00a0", " ").strip() + " руб."
    m2 = re.search(r"(\d[\d\s]*(?:[.,]\d{2})?)", s)
    if m2 and any(c.isdigit() for c in m2.group(1)):
        return m2.group(1).strip() + " руб."
    return None


def parse_gazprombank(pdf_bytes: bytes, text: str = "") -> dict:
    """Structured fields for Gazprombank Jasper card/SBP receipts."""
    if not text:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = doc[0].get_text() if doc.page_count else ""
            doc.close()
        except Exception:
            text = ""
    lines = _lines(text)
    pairs = _parse_gpb_pairs(lines)

    sender = pairs.get("Ф.И.О. отправителя")
    status = pairs.get("Статус операции")
    sender_card = pairs.get("Номер источника списания")
    receiver_card = pairs.get("Реквизиты карты получателя")
    purpose = pairs.get("Назначение платежа", "")

    amount = None
    if sender:
        for i, line in enumerate(lines):
            if line == sender:
                nxt = _next_nonempty(lines, i)
                if nxt:
                    amount = _format_amount(nxt)
                break
    if not amount:
        amount = _format_amount(pairs.get("Сумма", ""))

    title = "Чек Газпромбанк"
    if "карт" in purpose.lower():
        title = "Чек Газпромбанк по карте"
    elif "сбп" in purpose.lower() or "телефон" in purpose.lower():
        title = "Чек Газпромбанк СБП"

    contact_label = contact_value = None
    if receiver_card:
        contact_label, contact_value = "Карта получ", receiver_card

    bank_fields = extract_recipient_bank_fields(
        pdf_bytes,
        text,
        issuer_bank="Газпромбанк",
    )
    return {
        "title": title,
        "sender": sender,
        "receiver": None,
        "receiver_bank": bank_fields.get("recipient_bank_normalized") or None,
        "receiver_account": None,
        "status": status,
        "contact_label": contact_label,
        "contact_value": contact_value,
        "amount": amount,
        "sender_card": sender_card,
        "receiver_card": receiver_card,
        "is_sbp": "сбп" in purpose.lower(),
        **{k: bank_fields[k] for k in (
            "issuer_bank",
            "recipient_bank_raw",
            "recipient_bank_normalized",
            "recipient_bank_source",
            "sbp_route_profile",
        )},
        "fields": {
            "issuer_bank": bank_fields["issuer_bank"],
            "recipient_bank_raw": bank_fields["recipient_bank_raw"],
            "recipient_bank_normalized": bank_fields["recipient_bank_normalized"],
            "recipient_bank_source": bank_fields["recipient_bank_source"],
        },
    }


def parse_generic(pdf_bytes: bytes, text: str = "") -> dict:
    """Best-effort structured fields for any bank receipt."""
    if not text:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "".join(p.get_text() for p in doc)
            doc.close()
        except Exception:
            text = ""
    if _is_gpb_receipt(text):
        return parse_gazprombank(pdf_bytes, text)
    lines = _lines(text)
    channel = _detect_generic_channel(text)
    operation = _val(lines, _OPERATION_LABELS) or ""

    sender = _val_person(lines, _SENDER_LABELS)
    if sender and (_is_accountish(sender) or _looks_like_op_type(sender)):
        sender = None
    receiver = _val_person(lines, _RECEIVER_LABELS) or _val(lines, _RECEIVER_LABELS)
    if receiver and _looks_like_op_type(receiver):
        receiver = None
    rbank = _val(lines, _RBANK_LABELS)

    status = _val(lines, _STATUS_LABELS)
    if not status:
        for l in lines:
            if any(w in l.lower() for w in _OK_WORDS) and len(l) < 40:
                status = l
                break

    phone = _val(lines, _PHONE_LABELS, skip_footer=True)
    if phone:
        mp = _PHONE_RE.search(phone)
        phone = mp.group(0) if mp else phone

    sender_card = _val(lines, _SENDER_CARD_LABELS)
    receiver_card = _val(lines, _RECEIVER_CARD_LABELS) or _val(lines, _CARD_LABELS)

    amount_raw = _val(lines, _AMOUNT_LABELS) or ""
    amount = _format_amount(amount_raw)

    contact_label = contact_value = None
    if phone:
        contact_label, contact_value = "Телефон получ", phone
    elif receiver_card and (not receiver or channel == "card"):
        contact_label, contact_value = "Карта получ", receiver_card

    bank_fields = extract_recipient_bank_fields(pdf_bytes, text, issuer_bank="")
    if not bank_fields.get("recipient_bank_normalized") and rbank:
        bank_fields = {
            **bank_fields,
            "recipient_bank_raw": rbank,
            "recipient_bank_normalized": rbank,
            "recipient_bank_source": "explicit_pdf_field",
            "receiver_bank": rbank,
        }
    return {
        "sender": sender,
        "receiver": receiver,
        "receiver_bank": bank_fields.get("recipient_bank_normalized") or None,
        "receiver_account": None,
        "status": status,
        "contact_label": contact_label,
        "contact_value": contact_value,
        "amount": amount,
        "sender_card": sender_card,
        "receiver_card": receiver_card if channel == "card" or not phone else receiver_card,
        "transfer_channel": channel,
        "operation": operation,
        "is_sbp": channel == "sbp",
        **{k: bank_fields[k] for k in (
            "issuer_bank",
            "recipient_bank_raw",
            "recipient_bank_normalized",
            "recipient_bank_source",
            "sbp_route_profile",
        )},
        "fields": {
            "issuer_bank": bank_fields["issuer_bank"],
            "recipient_bank_raw": bank_fields["recipient_bank_raw"],
            "recipient_bank_normalized": bank_fields["recipient_bank_normalized"],
            "recipient_bank_source": bank_fields["recipient_bank_source"],
        },
    }
