"""
Email authenticity verification (anti-spoofing) for bank receipts.

The idea (same as competitors): the counterparty uses the *bank app's* own
"send receipt to email" feature and types one of OUR addresses. The bank's own
mail server then sends the message **directly** to us, so the cryptographic
proofs arrive intact and verifiable:

  * DKIM  — the message body+headers are signed by the bank's private key and
            verified against the public key published in the bank's DNS. A
            spoofer without the bank's private key cannot produce a valid
            signature.  -> the strongest, un-forgeable proof.
  * SPF   — the connecting IP must be authorised to send for the envelope
            domain. Checked at SMTP time (we know the client IP there).
  * From  — the visible From address must be a real bank address AND the DKIM
            signing domain (d=) must belong to the same bank.

verify_email() works on a raw RFC-822 message (bytes) and is fully testable
offline (DKIM needs DNS to fetch the public key; SPF needs the client IP).
"""

from __future__ import annotations

import re
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr

try:
    import dkim  # dkimpy
except Exception:  # pragma: no cover
    dkim = None

try:
    import spf as _spf  # pyspf
except Exception:  # pragma: no cover
    _spf = None


# ── Known bank sender domains ──────────────────────────────────────────────────
# Maps a sender / DKIM domain to the bank key used in detector.profiles.
# A genuine bank email's From domain AND DKIM d= must both be in this set for
# the same bank.
BANK_EMAIL_DOMAINS: dict[str, str] = {
    "tinkoff.ru": "tbank",
    "tbank.ru": "tbank",
    "cras.tinkoff.ru": "tbank",
    "email.tbank.ru": "tbank",
    "sberbank.ru": "sber",
    "sber.ru": "sber",
    "online.sberbank.ru": "sber",
    "alfabank.ru": "alfa",
    "alfabank.ds": "alfa",
    "vtb.ru": "vtb",
    "gazprombank.ru": "gazprom",
    "ozon.ru": "ozon",
    "ozonbank.ru": "ozon",
    "raiffeisen.ru": "raif",      # verified: From no-reply@raiffeisen.ru, d=raiffeisen.ru
    "psbank.ru": "psb",
    "otpbank.ru": "otp",          # verified: From noreply-dbo@otpbank.ru, d=otpbank.ru
    "uralsibbank.ru": "uralsib",  # verified: From client@uralsibbank.ru, d=uralsibbank.ru
    "uralsib.ru": "uralsib",
    "yandex.ru": "yandex",
    "bank.yandex.ru": "yandex",
}

BANK_NAMES: dict[str, str] = {
    "tbank": "Т-Банк", "sber": "Сбербанк", "alfa": "Альфа-Банк", "vtb": "ВТБ",
    "gazprom": "Газпромбанк", "ozon": "Озон Банк", "raif": "Райффайзенбанк",
    "psb": "ПСБ", "otp": "ОТП Банк", "uralsib": "Уралсиб", "yandex": "Яндекс Банк",
}

_DKIM_D_RE = re.compile(rb"[;\s]d=([^;\s]+)", re.I)


def _domain_of(addr: str) -> str:
    addr = (addr or "").strip().rstrip(">").lower()
    return addr.split("@")[-1] if "@" in addr else ""


def _registered(domain: str) -> str:
    """Reduce a host to its registered domain (last two labels)."""
    parts = (domain or "").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _bank_of(domain: str) -> str | None:
    domain = (domain or "").lower()
    if domain in BANK_EMAIL_DOMAINS:
        return BANK_EMAIL_DOMAINS[domain]
    return BANK_EMAIL_DOMAINS.get(_registered(domain))


def _dkim_domains(raw: bytes) -> list[str]:
    out = []
    for line in raw.split(b"\n"):
        if line[:15].lower().startswith(b"dkim-signature"):
            m = _DKIM_D_RE.search(line)
            if m:
                out.append(m.group(1).decode("ascii", "ignore").lower())
    # Header may continue on folded lines; scan the whole blob as a fallback.
    if not out:
        head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
        for m in _DKIM_D_RE.finditer(head):
            out.append(m.group(1).decode("ascii", "ignore").lower())
    return out


def _parse_sig_tags(value: str) -> dict:
    tags: dict[str, str] = {}
    for part in value.replace("\r", " ").replace("\n", " ").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = v.strip()
    return tags


def _bank_dkim_indices(msg: Message, from_bank: str) -> list[tuple[int, bool]]:
    """Indices of DKIM-Signature headers whose d= maps to `from_bank`.

    The index matches dkimpy's signature ordering (order of appearance). Each
    item is (index, has_body_length_tag).
    """
    out: list[tuple[int, bool]] = []
    for i, value in enumerate(msg.get_all("DKIM-Signature") or []):
        tags = _parse_sig_tags(value)
        d = tags.get("d", "").lower()
        if _bank_of(d) == from_bank:
            out.append((i, "l" in tags))
    return out


def _extract_pdfs(msg: Message) -> list[tuple[str, bytes]]:
    pdfs: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "").lower()
        fname = part.get_filename() or ""
        if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None
            if payload:
                pdfs.append((fname or "receipt.pdf", payload))
    return pdfs


def verify_email(
    raw_bytes: bytes,
    *,
    client_ip: str | None = None,
    mail_from: str | None = None,
) -> dict:
    """Verify a raw email's authenticity and pull out PDF attachments.

    Args:
        raw_bytes: the full RFC-822 message as received.
        client_ip: the IP that connected to our SMTP server (for SPF). Only
            available at receive time.
        mail_from: the SMTP envelope MAIL FROM (for SPF).

    Returns a dict describing the result (see keys below).
    """
    msg = message_from_bytes(raw_bytes)

    from_name, from_addr = parseaddr(msg.get("From", ""))
    from_domain = _domain_of(from_addr)

    # Return-Path carries the true envelope sender (SMTP MAIL FROM).
    # Use it as a fallback when From is absent/empty, and always expose it
    # so the UI can display the real originating address.
    rp_raw = msg.get("Return-Path", "") or ""
    _, rp_addr = parseaddr(rp_raw)
    if not rp_addr and "<" in rp_raw:
        rp_addr = rp_raw.strip().strip("<>").strip()
    rp_domain = _domain_of(rp_addr)

    # If From is blank, treat Return-Path as the visible sender.
    display_addr = from_addr or rp_addr
    display_domain = from_domain or rp_domain

    subject = str(msg.get("Subject", ""))

    from_bank = _bank_of(from_domain) or _bank_of(rp_domain)
    dkim_doms = _dkim_domains(raw_bytes)

    # Reject messages with more than one From header (header-injection / spoofing
    # ambiguity): which From the user sees may differ from what DKIM/DMARC bind to.
    multiple_from = len(msg.get_all("From") or []) > 1

    # ── DKIM with alignment ──────────────────────────────────────────────────────
    # It is NOT enough that *some* signature verifies and that *some* header carries
    # the bank's d=. We require: the signature whose d= maps to the From bank must
    # itself verify, and it must not use a body-length (l=) tag (which would let an
    # attacker append/replace the PDF after the signed region). This is DKIM-DMARC
    # alignment and defeats added-signature / replay tricks.
    dkim_aligned = False
    dkim_error = ""
    if dkim is not None and from_bank and not multiple_from:
        try:
            verifier = dkim.DKIM(raw_bytes)
            for idx, has_l in _bank_dkim_indices(msg, from_bank):
                if has_l:
                    dkim_error = "подпись с ограничением длины тела (l=) отклонена"
                    continue
                try:
                    if verifier.verify(idx):
                        dkim_aligned = True
                        break
                except Exception as e:
                    dkim_error = str(e)
        except Exception as e:
            dkim_error = str(e)

    # ── SPF with alignment ───────────────────────────────────────────────────────
    # SPF only counts if it passes AND the checked (envelope) domain belongs to the
    # same bank as the From address — otherwise an attacker passes SPF for their own
    # throwaway domain while showing a bank From.
    env = mail_from or from_addr
    env_domain = _domain_of(env)
    spf_result = "unknown"
    if _spf is not None and client_ip:
        try:
            spf_result, _ = _spf.check2(i=client_ip, s=env, h=env_domain)
        except Exception:
            spf_result = "unknown"
    spf_aligned = spf_result == "pass" and _bank_of(env_domain) == from_bank

    # Authentic iff From is a real bank address, the From header is unambiguous,
    # AND we have at least one *aligned* cryptographic/path proof tying THIS
    # message to that bank (DMARC logic).
    authentic = bool(from_bank and not multiple_from and (dkim_aligned or spf_aligned))

    bank_key = from_bank or next((b for d in dkim_doms if (b := _bank_of(d))), None)
    return {
        "authentic": authentic,
        "bank": bank_key,
        "bank_name": BANK_NAMES.get(bank_key, ""),
        "from": from_addr,
        "from_name": from_name,
        "from_domain": from_domain,
        "return_path": rp_addr,
        "return_path_domain": rp_domain,
        "display_addr": display_addr,   # best available sender address for UI
        "from_is_bank": bool(from_bank),
        "subject": subject,
        "dkim_pass": dkim_aligned,
        "dkim_aligned": dkim_aligned,
        "dkim_domains": dkim_doms,
        "dkim_bank_match": dkim_aligned,
        "dkim_error": dkim_error,
        "spf": spf_result,
        "spf_aligned": spf_aligned,
        "env_domain": env_domain,
        "multiple_from": multiple_from,
        "client_ip": client_ip,
        "pdfs": _extract_pdfs(msg),
    }
