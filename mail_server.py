"""
Inbound mail server — receives bank receipt emails and verifies their
authenticity (anti-spoofing), then pushes the verdict to the Telegram user.

Flow:
  1. Counterparty uses the bank app's "send receipt to email" and enters
     <nick>@<our-domain>.
  2. The bank's own mail server connects to us (port 25) and delivers the
     message directly  ->  DKIM signature + SPF (sender IP) arrive intact.
  3. We verify DKIM (un-forgeable bank signature), SPF (sender IP authorised),
     and that From is a real bank address.
  4. We extract the PDF and run the usual structural detector on it too.
  5. We resolve <nick> -> Telegram chat and deliver the result.

Run it as a separate process/systemd unit next to bot.py:

    MAIL_DOMAINS=checker.example.ru,dle.example.ru,mx.example.ru \
    BOT_TOKEN=... MAIL_PORT=25 py -3.13 mail_server.py

Requires inbound port 25 open and MX/DNS pointing at this host.
"""

import asyncio
import logging
import os
import time
import urllib.parse
import urllib.request

from aiosmtpd.controller import Controller
from dotenv import load_dotenv

import fitz

from detector import route as route_bank
from detector.email_check import verify_email
from detector import mailbox
from detector import reputation

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("mail")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
MAIL_HOST = os.getenv("MAIL_HOST", "0.0.0.0")


def _yn(v: bool) -> str:
    return "Да" if v else "Нет"


async def _tg_send(chat_id: int, text: str) -> None:
    """Fire a text verdict to Telegram via the HTTP API (no shared bot object)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    await asyncio.to_thread(
        lambda: urllib.request.urlopen(urllib.request.Request(url, data=data),
                                       timeout=15).read()
    )


def _multipart(fields: dict, fname: str, fdata: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body for sendDocument."""
    boundary = "----pdfmail" + os.urandom(8).hex()
    nl = b"\r\n"
    body = bytearray()
    for k, v in fields.items():
        body += b"--" + boundary.encode() + nl
        body += f'Content-Disposition: form-data; name="{k}"'.encode() + nl + nl
        body += str(v).encode() + nl
    body += b"--" + boundary.encode() + nl
    body += (f'Content-Disposition: form-data; name="document"; filename="{fname}"'
             ).encode() + nl
    body += b"Content-Type: application/pdf" + nl + nl
    body += fdata + nl
    body += b"--" + boundary.encode() + b"--" + nl
    return bytes(body), f"multipart/form-data; boundary={boundary}"


async def _tg_send_document(chat_id: int, fname: str, fdata: bytes,
                            caption: str) -> None:
    """Send the actual PDF file to the user with a caption."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    body, ctype = _multipart(
        {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
        fname or "receipt.pdf", fdata,
    )
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=30).read())


def _format_auth(res: dict) -> str:
    """Email-authenticity summary (sent as the leading text message)."""
    lines = ["📧 <b>Проверка чека по почте</b>", ""]

    # Best available address for display: From, else Return-Path
    from_addr = res.get("display_addr") or res["from"] or res.get("return_path") or "—"
    is_bank = res["from_is_bank"]
    authentic = res["authentic"]

    # ── Main verdict ──────────────────────────────────────────────────────────
    if authentic:
        lines.append("✅ <b>Письмо действительно отправлено банком</b>")
        lines.append(f"✉️ Отправитель: <b>{from_addr}</b>")
    elif not is_bank:
        # From address does not belong to any known bank — personal/fake domain
        lines.append("❌ <b>Чек пришел с личной почты отправителя:</b>")
        lines.append(f"<code>{from_addr}</code>")
        lines.append("")
        lines.append("<i>Настоящие чеки банк отправляет только со своего официального "
                     "адреса. Этот адрес банку не принадлежит — "
                     "письмо мог отправить кто угодно.</i>")
    else:
        # From is a bank address but DKIM/SPF failed — spoofed bank domain
        lines.append("❌ <b>Подлинность письма не подтверждена</b>")
        lines.append(f"✉️ Отправитель: <b>{from_addr}</b>")
        lines.append("")
        lines.append("<i>Адрес выглядит как банковский, но криптографическая подпись "
                     "не прошла — письмо могло быть подделано (спуфинг).</i>")

    # ── Technical details ─────────────────────────────────────────────────────
    lines.append("")
    dkim_txt = ("подпись подтверждена ✅" if res.get("dkim_aligned")
                else "не подтверждена ❌")
    lines.append(f"• DKIM: <b>{dkim_txt}</b>")
    if res.get("spf_aligned"):
        spf_txt = "pass ✅"
    elif res["spf"] == "pass":
        spf_txt = "pass ⚠️ (домен конверта ≠ банк)"
    else:
        spf_txt = {"fail": "fail ❌", "softfail": "softfail ⚠️"}.get(
            res["spf"], res["spf"] or "—")
    lines.append(f"• SPF: <b>{spf_txt}</b>")
    if res.get("multiple_from"):
        lines.append("• ⚠️ В письме несколько заголовков From — подозрительно")

    if not res["pdfs"]:
        lines += ["", "⚠️ В письме нет PDF-вложения с чеком."]
    elif len(res["pdfs"]) > 1:
        lines += [
            "",
            f"⚠️ В письме <b>{len(res['pdfs'])} PDF</b> — у банковского «отправить чек» "
            "обычно одно вложение; лишние файлы подозрительны.",
        ]
    return "\n".join(lines)


def _pdf_text(pdf: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
        t = "".join(p.get_text() for p in doc)
        doc.close()
        return t
    except Exception:
        return ""


_FAILED_STATUSES = {
    "неуспешно", "неуспешная", "не выполнен", "не выполнено",
    "отклонен", "отклонено", "отклонена", "отклонён",
    "ошибка", "отменен", "отменено", "отменена", "отменён",
    "failed", "rejected", "cancelled", "canceled", "error",
}


def _status_failed(status: str) -> bool:
    s = (status or "").lower().strip()
    return any(w in s for w in _FAILED_STATUSES)


def _operation_failed(status: str, result: dict) -> bool:
    """True if transfer did not complete — never show as successful original."""
    if _status_failed(status):
        return True
    details = result.get("details") or {}
    if str(details.get("operation_status_class") or "") == "FAILED_FINAL":
        return True
    notice = (
        result.get("status_notice")
        or details.get("status_warning")
        or ""
    ).lower()
    return "перевод не выполнен" in notice or _status_failed(notice)


def _format_caption(
    fname: str,
    pdf: bytes,
    chat_id: int,
    *,
    mail_authentic: bool = False,
) -> str:
    """Per-file caption — same detector path as Telegram bot uploads.

    If the enclosing email failed DKIM/SPF alignment, never present a green
    «чек банка» — swapped/extra attachments must not look like a confirmed
    original just because the PDF layer is clean.
    """
    lines = []
    try:
        bank, result, is_tbank = route_bank(pdf)
        verdict = (result.get("verdict") or "").upper()
        score = int(result.get("score") or 0)
        # Same binary rule as bot: ФЕЙК / score≥60
        is_fake = verdict in ("ФЕЙК", "FAKE") or score >= 60
        is_unknown = "НЕИЗВЕСТНЫЙ" in verdict or bank in (None, "", "Неизвестный банк")
        text = _pdf_text(pdf)

        if is_fake:
            try:
                from detector.reputation import KNOWN_FAKE_BY_SHA256, file_hash
                meta = KNOWN_FAKE_BY_SHA256.get(file_hash(pdf)) or {}
                custom = (meta.get("message") or "").strip()
            except Exception:
                custom = ""
            if custom:
                return "\n".join(["", custom])
            lines += ["", "❌ <b>Чек поддельный</b>"]
            for fl in result.get("flags", [])[:6]:
                lines.append(f"  • {fl}")
            return "\n".join(lines)

        if not mail_authentic:
            lines += [
                "",
                "⚠️ <b>PDF не принят: письмо не подтверждено</b>",
                "Структура вложения сама по себе не доказывает отправку банком "
                "(подмена вложения / лишний PDF / спуф). "
                "Нужен валидный DKIM/SPF банка.",
            ]
            if bank and not is_unknown:
                lines.append(f"Распознан эмитент по PDF: {bank} — без крипто-доказательства письма.")
            return "\n".join(lines)

        if is_unknown:
            lines += ["", "❓ <b>Банк не распознан</b>"]
            return "\n".join(lines)

        from detector.parser import parse as parse_tbank, format_receipt, parse_generic, parse_gazprombank
        try:
            if is_tbank:
                parsed = parse_tbank(pdf)
                title = parsed.get("title") or f"Чек {bank}"
            elif bank and "газпром" in bank.lower():
                parsed = parse_gazprombank(pdf, text)
                title = parsed.get("title") or f"Чек {bank}"
            else:
                parsed = parse_generic(pdf, text)
                title = f"Чек {bank}"
            parsed["issuer_bank"] = bank or parsed.get("issuer_bank") or ""
            body = format_receipt(parsed)
            status = parsed.get("status") or ""
            lines += ["", f"<code>{body}</code>", ""]
            if _operation_failed(status, result):
                st = status or "неуспешно"
                lines.append(f"❌ <b>Перевод не выполнен</b> ({bank})")
                lines.append(
                    f"Статус операции — «{st}». "
                    "Документ не является подтверждением оплаты."
                )
            else:
                lines.append(f"✅ <b>{title}</b>")
                um = (result.get("user_message") or "").strip()
                if um and len(um) < 800:
                    lines += ["", um]
        except Exception:
            if _operation_failed("", result):
                lines += ["", f"❌ <b>Перевод не выполнен</b> ({bank})"]
            else:
                lines += ["", f"✅ <b>Чек {bank}</b>"]

        try:
            reuse = reputation.check_email_reuse(pdf, text, chat_id)
            if reuse.get("reused") and reuse.get("by_other"):
                lines += [
                    "",
                    "⚠️ <b>Этот чек уже приходил по почте другому пользователю</b> "
                    f"(раз×{reuse.get('cnt', '?')}) — возможен повтор чужой квитанции.",
                ]
            elif reuse.get("reused"):
                lines += [
                    "",
                    f"ℹ️ Этот чек уже проверяли по почте ранее (раз×{reuse.get('cnt', '?')}).",
                ]
        except Exception:
            pass
    except Exception as e:
        log.exception("pdf analyze failed: %s", e)
        lines.append(f"• Не удалось разобрать PDF: {e}")
    return "\n".join(lines)


class Handler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        # Acknowledge fast; verification + Telegram delivery run in background so
        # the bank's SMTP client never waits on our heavy work (avoids timeouts).
        raw = bytes(envelope.content)
        client_ip = session.peer[0] if session.peer else None
        mail_from = envelope.mail_from
        rcpts = list(envelope.rcpt_tos)
        asyncio.ensure_future(self._process(raw, client_ip, mail_from, rcpts))
        return "250 Message accepted"

    async def _process(self, raw, client_ip, mail_from, rcpts):
        try:
            res = verify_email(raw, client_ip=client_ip, mail_from=mail_from)
        except Exception as e:
            log.exception("verify failed: %s", e)
            return

        log.info("mail from=%s dkim=%s spf=%s ip=%s rcpt=%s",
                 res["from"], res["dkim_pass"], res["spf"], client_ip, rcpts)

        for rcpt in rcpts:
            nick = rcpt.split("@", 1)[0].lower()
            chat_id = mailbox.chat_for_nick(nick)
            if chat_id is None:
                continue
            try:
                await _tg_send(chat_id, _format_auth(res))
                # Forward the receipt itself as a separate file with its details.
                for fname, pdf in res["pdfs"]:
                    caption = _format_caption(
                        fname, pdf, chat_id,
                        mail_authentic=bool(res.get("authentic")),
                    )
                    if len(caption) <= 1000:
                        await _tg_send_document(chat_id, fname, pdf, caption)
                    else:
                        await _tg_send_document(chat_id, fname, pdf,
                                                f"📄 <b>{fname}</b>")
                        await _tg_send(chat_id, caption)
            except Exception as e:
                log.warning("tg send failed for %s: %s", chat_id, e)


def _tls_context():
    """Return an SSL context if Let's Encrypt cert exists, else None."""
    import ssl
    domain = (mailbox.domains() or [""])[0]
    cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key  = f"/etc/letsencrypt/live/{domain}/privkey.pem"
    if os.path.exists(cert) and os.path.exists(key):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(cert, key)
        log.info("TLS enabled with cert %s", cert)
        return ctx
    log.info("No TLS cert found at %s — running plain SMTP", cert)
    return None


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    if not mailbox.domains():
        raise RuntimeError("MAIL_DOMAINS не заданы (домены приёма почты)")

    tls_ctx = _tls_context()
    kwargs = {"hostname": MAIL_HOST, "port": MAIL_PORT}
    if tls_ctx:
        # STARTTLS: advertise STARTTLS, upgrade on demand
        kwargs["tls_context"] = tls_ctx
        kwargs["require_starttls"] = False  # accept both for compatibility

    controller = Controller(Handler(), **kwargs)
    controller.start()
    log.info("Mail server on %s:%s, domains=%s, tls=%s",
             MAIL_HOST, MAIL_PORT, mailbox.domains(), tls_ctx is not None)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        controller.stop()


if __name__ == "__main__":
    main()
