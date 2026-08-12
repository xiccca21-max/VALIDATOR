# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot\mail_server.py")
t = p.read_text(encoding="utf-8")
start = t.find("def _format_caption")
end = t.find("\nclass Handler:")
if start < 0 or end < 0:
    raise SystemExit(f"markers missing {start} {end}")

new = '''def _format_caption(fname: str, pdf: bytes, chat_id: int) -> str:
    """Per-file caption — same detector path as Telegram bot uploads."""
    lines = []
    try:
        bank, result, is_tbank = route_bank(pdf)
        verdict = (result.get("verdict") or "").upper()
        score = int(result.get("score") or 0)
        is_fake = verdict in ("ФЕЙК", "FAKE") or score >= 60
        is_unknown = "НЕИЗВЕСТНЫЙ" in verdict or bank in (None, "", "Неизвестный банк")
        text = _pdf_text(pdf)

        if is_fake:
            lines += ["", "❌ <b>Чек поддельный</b>"]
            for fl in result.get("flags", [])[:6]:
                lines.append(f"  • {fl}")
            return "\\n".join(lines)

        if is_unknown:
            lines += ["", "❓ <b>Банк не распознан</b>"]
            return "\\n".join(lines)

        from detector.parser import (
            parse as parse_tbank, format_receipt, parse_generic, parse_gazprombank,
        )
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
            lines += ["", f"<code>{body}</code>", "", f"✅ <b>{title}</b>"]
            um = (result.get("user_message") or "").strip()
            if um and len(um) < 800:
                lines += ["", um]
        except Exception:
            lines += ["", f"✅ <b>Чек {bank}</b>"]

        try:
            reputation.check_email_reuse(pdf, text, chat_id)
        except Exception:
            pass
    except Exception as e:
        log.exception("pdf analyze failed: %s", e)
        lines.append(f"• Не удалось разобрать PDF: {e}")
    return "\\n".join(lines)


'''
# Convert intentional \\n in source to real backslash-n for Python source of join
new = new.replace('return "\\n".join', 'return "\\n".join')  # no-op placeholder

# Build with real newlines in joins by using chr
join_expr = '"\\n".join'
# Actually in a normal Python file we need the two characters \ and n inside quotes.
new = new.replace('\\\\n', '\\n')  # if doubled
# The string new currently has literal \\n from the triple-quoted raw-ish content.
# In the ''' string above, \\n becomes \n (one backslash + n) in the Python string value.
# That's correct for writing to the .py file.

t = t[:start] + new + t[end + 1 :]
p.write_text(t, encoding="utf-8")
print("patched ok", p.stat().st_size)
# sanity: ensure join exists
assert 'return "\\n".join(lines)' in t or 'return "\n".join(lines)' in p.read_text(encoding="utf-8")
print("join ok")
